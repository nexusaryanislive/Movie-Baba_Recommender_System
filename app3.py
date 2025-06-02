import streamlit as st
import pickle
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry # Correct import for Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. Load Data ---
# Ensure these files are in the same directory as app.py or provide the full path
try:
    with open('movie_dict.pkl', 'rb') as f:
        movie_list_data = pickle.load(f)
    movies = pd.DataFrame(movie_list_data)
    
    with open('similarity.pkl', 'rb') as f:
        similarity = pickle.load(f)
except FileNotFoundError:
    st.error("Error: 'movie_dict.pkl' or 'similarity.pkl' not found. Please ensure these files are present.")
    st.stop() # Stop the app if data files are missing
except Exception as e:
    st.error(f"Error loading data files: {e}")
    st.stop()

# --- 2. Define Robust and Cached Poster Fetching Function ---
@st.cache_data(ttl="6h") # Cache results for 6 hours
def fetch_poster_robust_cached(movie_tmdb_id):
    api_key = "8c9ed4a92c476df16b161ba03d1e0430" # Your TMDB API key
    url = f"https://api.themoviedb.org/3/movie/{movie_tmdb_id}?api_key={api_key}&language=en-US"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; StreamlitMovieApp/1.0)"} # Be a good internet citizen
    
    placeholder_no_poster = "https://via.placeholder.com/500x750.png?text=No+Poster+Available"
    placeholder_error = "https://via.placeholder.com/500x750.png?text=Error+Loading+Poster"

    # Setup retry strategy for the HTTP session
    retry_strategy = Retry(
        total=3,                # Total number of retries
        backoff_factor=1,       # Time to wait between retries (1s, 2s, 4s)
        status_forcelist=[429, 500, 502, 503, 504], # HTTP status codes to retry on
        allowed_methods=["HEAD", "GET", "OPTIONS"]  # HTTP methods to retry
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    http_session = requests.Session()
    http_session.mount("https://", adapter)
    http_session.mount("http://", adapter) # Though TMDB uses https, good practice

    try:
        # Increased timeout to 10 seconds for the request
        response = http_session.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4XX or 5XX)
        
        data = response.json()
        poster_path = data.get('poster_path')
        
        if poster_path:
            return f"https://image.tmdb.org/t/p/w500/{poster_path}"
        else:
            print(f"No poster path found via API for movie_id={movie_tmdb_id}. Movie data: {data.get('title', 'N/A')}")
            return placeholder_no_poster
            
    except requests.exceptions.Timeout:
        print(f"Timeout (10s) occurred when fetching poster for movie_id={movie_tmdb_id}. URL: {url}")
        return placeholder_error
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error occurred for movie_id={movie_tmdb_id}: {e}. Status code: {e.response.status_code if e.response else 'N/A'}. Response: {e.response.text[:200] if e.response else 'N/A'}")
        return placeholder_error
    except requests.exceptions.RequestException as e: 
        print(f"A general request failed for movie_id={movie_tmdb_id}: {e}")
        return placeholder_error
    except ValueError as e: # Includes JSONDecodeError if response isn't valid JSON
        response_text = ""
        if 'response' in locals() and response is not None:
            response_text = response.text[:200]
        print(f"Failed to decode JSON or other ValueError for movie_id={movie_tmdb_id}: {e}. Response text: {response_text}")
        return placeholder_error
    except Exception as e: # Catch any other unexpected errors
        print(f"An unexpected error occurred fetching poster for movie_id={movie_tmdb_id}: {type(e).__name__} - {e}")
        return placeholder_error
    finally:
        http_session.close() # Ensure the session is closed

# --- 3. Define Recommendation Function with Concurrent Fetching ---
def recommend_movies_final(movie_selected_title):
    try:
        movie_index = movies[movies['title'] == movie_selected_title].index[0]
    except IndexError:
        print(f"Movie '{movie_selected_title}' not found in the DataFrame.")
        return [], [] # Return empty lists if movie not found

    distances = similarity[movie_index]
    # Sort by similarity score, skip the first one (itself), and take top 5
    # movies_list_indices will contain (original_dataframe_index, similarity_score)
    movies_list_indices_scores = sorted(list(enumerate(distances)), reverse=True, key=lambda x: x[1])[1:6]
    
    # Prepare data for concurrent fetching
    recommended_movies_data_to_fetch = []
    for i, (original_df_index, _) in enumerate(movies_list_indices_scores):
        if original_df_index < len(movies): # Boundary check
            movie_tmdb_id = movies.iloc[original_df_index].id # Assuming 'id' column stores TMDB ID
            title = movies.iloc[original_df_index].title
            recommended_movies_data_to_fetch.append({'tmdb_id': movie_tmdb_id, 'title': title, 'original_order': i})
        else:
            print(f"Warning: Original index {original_df_index} out of bounds for movies DataFrame.")

    if not recommended_movies_data_to_fetch:
        return [], []

    # Initialize maps to store results, preserving order
    posters_map = {} # tmdb_id -> poster_url
    titles_map = {}  # tmdb_id -> title

    # Use ThreadPoolExecutor for concurrent fetching
    # Adjust max_workers based on API limits and typical latency; 5 is usually fine for TMDB.
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Submit tasks to fetch posters; future_to_movie_info maps future object to its input data
        future_to_movie_info = {
            executor.submit(fetch_poster_robust_cached, movie_info['tmdb_id']): movie_info
            for movie_info in recommended_movies_data_to_fetch
        }
        
        for future in as_completed(future_to_movie_info):
            movie_info = future_to_movie_info[future]
            tmdb_id = movie_info['tmdb_id']
            title = movie_info['title']
            try:
                poster_url = future.result() # Get the result from the completed future
                posters_map[tmdb_id] = poster_url
                titles_map[tmdb_id] = title
            except Exception as exc:
                print(f"Movie '{title}' (ID: {tmdb_id}) generated an exception during concurrent fetch: {exc}")
                posters_map[tmdb_id] = "https://via.placeholder.com/500x750.png?text=Error+Processing" # Fallback
                titles_map[tmdb_id] = title # Still keep the title

    # Reconstruct lists in the correct original recommendation order
    num_recommendations = len(recommended_movies_data_to_fetch)
    ordered_titles = [None] * num_recommendations
    ordered_posters = [None] * num_recommendations

    for movie_info in recommended_movies_data_to_fetch:
        order_idx = movie_info['original_order']
        tmdb_id = movie_info['tmdb_id']
        ordered_titles[order_idx] = titles_map.get(tmdb_id, "Title Not Found")
        ordered_posters[order_idx] = posters_map.get(tmdb_id, "https://via.placeholder.com/500x750.png?text=Poster+Not+Found")
        
    return ordered_titles, ordered_posters

# --- 4. Streamlit UI ---
st.set_page_config(layout="wide") # Optional: Use wide layout
st.title('🎬 Movie Baba - Recommender')

# Check if movies DataFrame is loaded and has 'title' column
if 'title' not in movies.columns:
    st.error("DataFrame 'movies' does not contain a 'title' column. Please check 'movie_dict.pkl'.")
    st.stop()

movie_selected_title = st.selectbox(
    "🍿 Select a movie you recently watched:",
    movies['title'].values,
    index=None, # No default selection
    placeholder="Type or select a movie..."
)

if st.button('✨ Get Recommendations', use_container_width=True, type="primary"):
    if movie_selected_title:
        with st.spinner(f"Finding recommendations based on '{movie_selected_title}'..."):
            recommended_titles, recommended_posters = recommend_movies_final(movie_selected_title)

        if recommended_titles and recommended_posters:
            st.subheader(f"Recommended Movies for You (based on {movie_selected_title}):")
            
            # Dynamically create columns based on number of recommendations
            num_recommendations = len(recommended_titles)
            if num_recommendations > 0:
                cols = st.columns(num_recommendations)
                for i in range(num_recommendations):
                    with cols[i]:
                        st.markdown(f"**{recommended_titles[i]}**")
                        if recommended_posters[i]:
                            st.image(recommended_posters[i], use_column_width='always')
                        else:
                            st.caption("Poster not available")
            else:
                st.warning("No recommendations found for this movie. This could be due to data limitations or API issues.")

        else:
            st.error("Sorry, couldn't fetch recommendations. Please try another movie or check the console for errors.")
    else:
        st.warning("Please select a movie first!")

st.markdown("---")
st.caption("Powered by Streamlit and The Movie Database (TMDB) API")