import streamlit as st
import pickle
import pandas as pd
import requests
import logging

movie_list = pickle.load(open('movie_dict.pkl', 'rb'))
movies = pd.DataFrame(movie_list)
similarity = pickle.load(open('similarity.pkl', 'rb'))

logging.basicConfig(level=logging.INFO)

def fetch_poster(movie_id, fallback_text="No+Image"):
    """
    Fetches the movie poster URL from TMDb API.

    Args:
        movie_id (int or str): The TMDb movie ID.
        fallback_text (str): Text to show on fallback image if poster not found.

    Returns:
        str: URL of the poster image or a fallback placeholder.
    """
    base_url = "https://api.themoviedb.org/3/movie"
    image_base_url = "https://image.tmdb.org/t/p/w500/"
    placeholder_url = f"https://via.placeholder.com/500x750.png?text={fallback_text}"

    try:
        url = f"{base_url}/{movie_id}?api_key=b76bb27542ba7b7652281b79d2905180&language=en-US"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()
        poster_path = data.get('poster_path')

        if poster_path:
            return image_base_url + poster_path
        else:
            logging.warning(f"No poster found for movie ID: {movie_id}")
            return placeholder_url

    except requests.RequestException as e:
        logging.error(f"Request error for movie ID {movie_id}: {e}")
    except ValueError as e:
        logging.error(f"JSON decoding error for movie ID {movie_id}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error for movie ID {movie_id}: {e}")

    return f"https://via.placeholder.com/500x750.png?text=Error"


def recommend_movies(movie_selected):
    movie_index = movies[movies['title'] == movie_selected].index[0]
    distance = similarity[movie_index]
    movies_list = sorted(list(enumerate(distance)), reverse = True, key = lambda x : x[1])[1:6]
    recommended_movies = []
    movie_poster = [] 
    for i in movies_list:
        movie_id = movies.iloc[i[0]].id
        movie_poster.append(fetch_poster(movie_id))
        recommended_movies.append(movies.iloc[i[0]].title)
    return recommended_movies, movie_poster


st.title('Movie Baba')

movie_selected = st.selectbox(
    "Select your recently watched movie",
    movies['title'].values
)

if st.button('Recommend'):
    recommendations, poster = recommend_movies(movie_selected)

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.text(recommendations[0])
        st.image(poster[0])
    with col2:
        st.text(recommendations[1])
        st.image(poster[1])
    with col3:
        st.text(recommendations[2])
        st.image(poster[2])
    with col4:
        st.text(recommendations[3])
        st.image(poster[3])
    with col5:
        st.text(recommendations[4])
        st.image(poster[4])


