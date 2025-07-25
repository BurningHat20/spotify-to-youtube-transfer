# Music Transfer: Spotify to YouTube Music

A Flask web application to transfer your liked songs from Spotify to a new playlist on YouTube Music. The app uses the Spotify API to fetch your saved tracks and the YouTube Data API to search for those tracks and add them to a playlist on your YouTube account.

![Python](https://img.shields.io/badge/Python-3.11-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-black.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- **Secure Authentication**: Uses OAuth2 for both Spotify and YouTube, ensuring your credentials are safe.
- **Full Library Sync**: Fetches your entire library of liked songs from Spotify.
- **Smart Matching**: Searches YouTube for the best video match for each song.
- **Automatic Playlist Creation**: Creates a new, private playlist on your YouTube account.
- **Real-time Progress**: A web UI that tracks the transfer progress in real-time, showing total, processed, successful, and failed songs.
- **Persistent Sessions**: Uses a local SQLite database to manage user sessions and transfer progress, allowing you to see past results.
- **Responsive UI**: A clean and responsive interface built with Bootstrap.

## Demo / Screenshots

_(It is highly recommended to add a few screenshots or a GIF of the application in action here. For example: the home page, the connection status, and the transfer progress.)_

![Home Page](placeholder.png)
![Transfer Progress](placeholder.png)

## Technology Stack

- **Backend**: Flask, Python
- **Database**: SQLite
- **APIs**:
  - [Spotipy](https://spotipy.readthedocs.io/) (Spotify Web API)
  - [Google API Python Client](https://github.com/googleapis/google-api-python-client) (YouTube Data API v3)
- **Frontend**: HTML, Bootstrap 5, JavaScript
- **Environment Management**: python-dotenv

## Project Structure

```
yt-to-spotify/
┣ 📂static/
┣ 📂templates/
┃ ┣ 📜index.html         # Main UI (Bootstrap)
┃ ┗ 📜redesigned.html    # Alternative UI (TailwindCSS)
┣ 📜.example.env
┣ 📜.gitignore
┣ 📜app.py               # Main Flask application
┣ 📜music_transfer.db    # SQLite database (created on run)
┗ 📜requirements.txt
```

## Setup and Installation

Follow these steps to get the application running on your local machine.

### 1. Prerequisites

- [Python 3.9+](https://www.python.org/downloads/)
- [Git](https://git-scm.com/)

### 2. Clone the Repository

```bash
git clone <your-repository-url>
cd yt-to-spotify
```

### 3. Set Up a Virtual Environment

It's recommended to use a virtual environment to manage dependencies.

- **On Windows:**
  ```bash
  python -m venv venv
  venv\Scripts\activate
  ```
- **On macOS/Linux:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. API Configuration (Crucial Step)

You need to get API keys from both Spotify and Google.

1.  **Create the `.env` file**:
    Make a copy of the example environment file and name it `.env`.

    ```bash
    # On Windows
    copy .example.env .env

    # On macOS/Linux
    cp .example.env .env
    ```

2.  **Set up Spotify API Credentials**:

    - Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and log in.
    - Click `Create app`.
    - Give it a name (e.g., "Music Transfer") and description.
    - Once created, copy the `Client ID` and `Client Secret` into your `.env` file.
    - Go to `Edit Settings` for your app.
    - In the `Redirect URIs` field, add: `https://127.0.0.1:5000/spotify/callback`
    - Save your changes.

3.  **Set up YouTube Data API Credentials**:

    - Go to the [Google Cloud Console](https://console.cloud.google.com/).
    - Create a new project.
    - In the sidebar, navigate to `APIs & Services` > `Enabled APIs & services`.
    - Click `+ ENABLE APIS AND SERVICES`, search for "YouTube Data API v3", and enable it.
    - Go to `APIs & Services` > `OAuth consent screen`.
      - Choose `External` and click `Create`.
      - Fill in the required fields (app name, user support email, developer contact). You can leave the rest blank for now. Save and continue.
      - On the `Scopes` page, click `Add or Remove Scopes`, find the YouTube Data API, and select the `.../auth/youtube` scope.
      - Add yourself as a test user.
    - Go to `APIs & Services` > `Credentials`.
      - Click `+ CREATE CREDENTIALS` and select `OAuth client ID`.
      - For `Application type`, select `Web application`.
      - Under `Authorized redirect URIs`, click `+ ADD URI` and enter: `https://127.0.0.1:5000/youtube/callback`
      - Click `Create`.
      - A window will pop up with your `Client ID` and `Client Secret`. Copy these into your `.env` file.

4.  **Final `.env` file**:
    Your `.env` file should now look something like this:

    ```properties
    SECRET_KEY=a_very_long_random_string_for_flask_sessions

    SPOTIFY_CLIENT_ID=your_spotify_client_id
    SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
    SPOTIFY_REDIRECT_URI=https://127.0.0.1:5000/spotify/callback

    YOUTUBE_CLIENT_ID=your_youtube_client_id
    YOUTUBE_CLIENT_SECRET=your_youtube_client_secret
    YOUTUBE_REDIRECT_URI=https://127.0.0.1:5000/youtube/callback
    ```

### 6. Run the Application

```bash
python app.py
```

The application will start with a self-signed SSL certificate, which is required for the OAuth callbacks.

- Open your browser and navigate to **`https://127.0.0.1:5000`**.
- You will likely see a security warning ("Your connection is not private"). This is expected. Click `Advanced` and then `Proceed to 127.0.0.1 (unsafe)`.

## How to Use

1.  **Connect Services**: On the main page, click `Connect Spotify` and then `Connect YouTube`. You will be redirected to authorize the application for each service.
2.  **Fetch Songs**: Once both services are connected, click the `Fetch Liked Songs` button. This will load all of your saved tracks from Spotify.
3.  **Start Transfer**: You can provide an optional name for your new YouTube playlist. Click `Start Transfer` to begin the process.
4.  **Monitor Progress**: The UI will update in real-time, showing you which songs are being processed and whether they were successfully found and added to your new playlist.
5.  **View Playlist**: Once the transfer is complete, a link to the new YouTube playlist will appear.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue if you have suggestions or find a bug.
