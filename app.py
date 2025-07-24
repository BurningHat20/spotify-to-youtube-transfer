from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
import os
import json
import time
import sqlite3
from datetime import datetime
import logging
from dotenv import load_dotenv
import uuid
from contextlib import contextmanager

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-change-this')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DATABASE_PATH = 'music_transfer.db'

# Spotify Configuration
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'https://127.0.0.1:5000/spotify/callback')

# YouTube Configuration
YOUTUBE_CLIENT_ID = os.getenv('YOUTUBE_CLIENT_ID')
YOUTUBE_CLIENT_SECRET = os.getenv('YOUTUBE_CLIENT_SECRET')
YOUTUBE_REDIRECT_URI = os.getenv('YOUTUBE_REDIRECT_URI', 'https://127.0.0.1:5000/youtube/callback')

# OAuth2 Scopes - Updated to include the scopes Google automatically adds
SPOTIFY_SCOPES = 'user-library-read user-read-private user-read-email'
YOUTUBE_SCOPES = [
    'https://www.googleapis.com/auth/youtube',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_database()
    
    @contextmanager
    def get_db_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_database(self):
        """Initialize database tables"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            
            # User sessions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id TEXT PRIMARY KEY,
                    spotify_token TEXT,
                    spotify_user_id TEXT,
                    youtube_credentials TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Songs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    spotify_id TEXT,
                    name TEXT,
                    artist TEXT,
                    album TEXT,
                    duration_ms INTEGER,
                    external_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES user_sessions (id)
                )
            ''')
            
            # Transfer data table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    playlist_id TEXT,
                    playlist_name TEXT,
                    total_songs INTEGER,
                    processed INTEGER DEFAULT 0,
                    successful INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES user_sessions (id)
                )
            ''')
            
            # Transfer results table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transfer_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transfer_id INTEGER,
                    song_id INTEGER,
                    youtube_video_id TEXT,
                    youtube_title TEXT,
                    youtube_channel TEXT,
                    youtube_thumbnail TEXT,
                    status TEXT,
                    added_to_playlist BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (transfer_id) REFERENCES transfers (id),
                    FOREIGN KEY (song_id) REFERENCES songs (id)
                )
            ''')
            
            conn.commit()
    
    def get_or_create_session(self, session_id):
        """Get or create a user session"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM user_sessions WHERE id = ?', (session_id,))
            result = cursor.fetchone()
            
            if not result:
                cursor.execute(
                    'INSERT INTO user_sessions (id) VALUES (?)',
                    (session_id,)
                )
                conn.commit()
                cursor.execute('SELECT * FROM user_sessions WHERE id = ?', (session_id,))
                result = cursor.fetchone()
            
            return dict(result) if result else None
    
    def update_spotify_token(self, session_id, token_info, user_id=None):
        """Update Spotify token for a session"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE user_sessions 
                SET spotify_token = ?, spotify_user_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (json.dumps(token_info), user_id, session_id))
            conn.commit()
    
    def update_youtube_credentials(self, session_id, credentials):
        """Update YouTube credentials for a session"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE user_sessions 
                SET youtube_credentials = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (json.dumps(credentials), session_id))
            conn.commit()
    
    def get_spotify_token(self, session_id):
        """Get Spotify token for a session"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT spotify_token FROM user_sessions WHERE id = ?', (session_id,))
            result = cursor.fetchone()
            return json.loads(result['spotify_token']) if result and result['spotify_token'] else None
    
    def get_youtube_credentials(self, session_id):
        """Get YouTube credentials for a session"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT youtube_credentials FROM user_sessions WHERE id = ?', (session_id,))
            result = cursor.fetchone()
            return json.loads(result['youtube_credentials']) if result and result['youtube_credentials'] else None
    
    def store_songs(self, session_id, songs):
        """Store songs for a session"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Clear existing songs for this session
            cursor.execute('DELETE FROM songs WHERE session_id = ?', (session_id,))
            
            # Insert new songs
            for song in songs:
                cursor.execute('''
                    INSERT INTO songs (session_id, spotify_id, name, artist, album, duration_ms, external_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session_id,
                    song['id'],
                    song['name'],
                    song['artist'],
                    song['album'],
                    song['duration_ms'],
                    song['external_url']
                ))
            
            conn.commit()
    
    def get_songs(self, session_id):
        """Get songs for a session"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM songs WHERE session_id = ? ORDER BY id', (session_id,))
            results = cursor.fetchall()
            
            songs = []
            for row in results:
                songs.append({
                    'id': row['spotify_id'],
                    'name': row['name'],
                    'artist': row['artist'],
                    'album': row['album'],
                    'duration_ms': row['duration_ms'],
                    'external_url': row['external_url'],
                    'db_id': row['id']
                })
            
            return songs
    
    def create_transfer(self, session_id, playlist_id, playlist_name, total_songs):
        """Create a new transfer record"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transfers (session_id, playlist_id, playlist_name, total_songs)
                VALUES (?, ?, ?, ?)
            ''', (session_id, playlist_id, playlist_name, total_songs))
            conn.commit()
            return cursor.lastrowid
    
    def get_active_transfer(self, session_id):
        """Get active transfer for a session"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM transfers 
                WHERE session_id = ? AND status != 'completed'
                ORDER BY created_at DESC LIMIT 1
            ''', (session_id,))
            result = cursor.fetchone()
            return dict(result) if result else None
    
    def update_transfer_progress(self, transfer_id, processed=None, successful=None, failed=None, status=None):
        """Update transfer progress"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if processed is not None:
                updates.append('processed = ?')
                params.append(processed)
            if successful is not None:
                updates.append('successful = ?')
                params.append(successful)
            if failed is not None:
                updates.append('failed = ?')
                params.append(failed)
            if status is not None:
                updates.append('status = ?')
                params.append(status)
            
            if updates:
                updates.append('updated_at = CURRENT_TIMESTAMP')
                params.append(transfer_id)
                
                query = f'UPDATE transfers SET {", ".join(updates)} WHERE id = ?'
                cursor.execute(query, params)
                conn.commit()
    
    def add_transfer_result(self, transfer_id, song_db_id, youtube_result=None, status='not_found', added_to_playlist=False):
        """Add a transfer result"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transfer_results 
                (transfer_id, song_id, youtube_video_id, youtube_title, youtube_channel, youtube_thumbnail, status, added_to_playlist)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transfer_id,
                song_db_id,
                youtube_result['video_id'] if youtube_result else None,
                youtube_result['title'] if youtube_result else None,
                youtube_result['channel'] if youtube_result else None,
                youtube_result['thumbnail'] if youtube_result else None,
                status,
                added_to_playlist
            ))
            conn.commit()
    
    def get_transfer_results(self, transfer_id):
        """Get transfer results"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT tr.*, s.name as song_name, s.artist, s.album, s.spotify_id
                FROM transfer_results tr
                JOIN songs s ON tr.song_id = s.id
                WHERE tr.transfer_id = ?
                ORDER BY tr.id
            ''', (transfer_id,))
            
            results = []
            for row in cursor.fetchall():
                youtube_match = None
                if row['youtube_video_id']:
                    youtube_match = {
                        'video_id': row['youtube_video_id'],
                        'title': row['youtube_title'],
                        'channel': row['youtube_channel'],
                        'thumbnail': row['youtube_thumbnail']
                    }
                
                results.append({
                    'song': {
                        'id': row['spotify_id'],
                        'name': row['song_name'],
                        'artist': row['artist'],
                        'album': row['album']
                    },
                    'youtube_match': youtube_match,
                    'status': row['status'],
                    'added_to_playlist': bool(row['added_to_playlist'])
                })
            
            return results
    
    def disconnect_service(self, session_id, service):
        """Disconnect a service for a session"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            
            if service == 'spotify':
                cursor.execute('''
                    UPDATE user_sessions 
                    SET spotify_token = NULL, spotify_user_id = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (session_id,))
                # Also clear songs
                cursor.execute('DELETE FROM songs WHERE session_id = ?', (session_id,))
            elif service == 'youtube':
                cursor.execute('''
                    UPDATE user_sessions 
                    SET youtube_credentials = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (session_id,))
            
            conn.commit()
    
    def clear_session_data(self, session_id):
        """Clear all data for a session"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Delete in correct order due to foreign key constraints
            cursor.execute('DELETE FROM transfer_results WHERE transfer_id IN (SELECT id FROM transfers WHERE session_id = ?)', (session_id,))
            cursor.execute('DELETE FROM transfers WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM songs WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM user_sessions WHERE id = ?', (session_id,))
            
            conn.commit()

# Initialize database
db_manager = DatabaseManager(DATABASE_PATH)

# Initialize Spotify OAuth
def get_spotify_oauth():
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPES,
        cache_path=None
    )

# Initialize YouTube OAuth Flow
def get_youtube_flow():
    return Flow.from_client_config(
        {
            "web": {
                "client_id": YOUTUBE_CLIENT_ID,
                "client_secret": YOUTUBE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [YOUTUBE_REDIRECT_URI]
            }
        },
        scopes=YOUTUBE_SCOPES
    )

def get_session_id():
    """Get or create session ID"""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']

class MusicTransferService:
    def __init__(self):
        self.spotify = None
        self.youtube = None
        
    def set_spotify_client(self, token_info):
        """Initialize Spotify client with token"""
        try:
            self.spotify = spotipy.Spotify(auth=token_info['access_token'])
            return True
        except Exception as e:
            logger.error(f"Error setting Spotify client: {e}")
            return False
    
    def set_youtube_client(self, credentials):
        """Initialize YouTube client with credentials"""
        try:
            self.youtube = build('youtube', 'v3', credentials=credentials)
            return True
        except Exception as e:
            logger.error(f"Error setting YouTube client: {e}")
            return False
    
    def get_spotify_liked_songs(self):
        """Fetch all liked songs from Spotify"""
        if not self.spotify:
            raise Exception("Spotify client not initialized")
        
        songs = []
        results = self.spotify.current_user_saved_tracks(limit=50)
        
        while results:
            for item in results['items']:
                track = item['track']
                songs.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artist': ', '.join([artist['name'] for artist in track['artists']]),
                    'album': track['album']['name'],
                    'duration_ms': track['duration_ms'],
                    'external_url': track['external_urls']['spotify']
                })
            
            if results['next']:
                results = self.spotify.next(results)
            else:
                break
        
        return songs
    
    def search_youtube_video(self, song_name, artist_name):
        """Search for a song on YouTube"""
        if not self.youtube:
            raise Exception("YouTube client not initialized")
        
        query = f"{song_name} {artist_name}"
        
        try:
            search_response = self.youtube.search().list(
                q=query,
                part='id,snippet',
                maxResults=5,
                type='video',
                videoCategoryId='10'  # Music category
            ).execute()
            
            # Return the best match (first result)
            if search_response['items']:
                video = search_response['items'][0]
                return {
                    'video_id': video['id']['videoId'],
                    'title': video['snippet']['title'],
                    'channel': video['snippet']['channelTitle'],
                    'thumbnail': video['snippet']['thumbnails']['default']['url']
                }
            return None
            
        except Exception as e:
            logger.error(f"Error searching YouTube for {query}: {e}")
            return None
    
    def create_youtube_playlist(self, title, description=""):
        """Create a new YouTube playlist"""
        if not self.youtube:
            raise Exception("YouTube client not initialized")
        
        try:
            playlist_response = self.youtube.playlists().insert(
                part='snippet,status',
                body={
                    'snippet': {
                        'title': title,
                        'description': description
                    },
                    'status': {
                        'privacyStatus': 'private'
                    }
                }
            ).execute()
            
            return playlist_response['id']
            
        except Exception as e:
            logger.error(f"Error creating YouTube playlist: {e}")
            raise e
    
    def add_video_to_playlist(self, playlist_id, video_id):
        """Add a video to YouTube playlist"""
        if not self.youtube:
            raise Exception("YouTube client not initialized")
        
        try:
            self.youtube.playlistItems().insert(
                part='snippet',
                body={
                    'snippet': {
                        'playlistId': playlist_id,
                        'resourceId': {
                            'kind': 'youtube#video',
                            'videoId': video_id
                        }
                    }
                }
            ).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error adding video {video_id} to playlist {playlist_id}: {e}")
            return False

# Initialize service
transfer_service = MusicTransferService()

@app.route('/')
def index():
    """Main page"""
    session_id = get_session_id()
    db_manager.get_or_create_session(session_id)
    
    spotify_token = db_manager.get_spotify_token(session_id)
    youtube_credentials = db_manager.get_youtube_credentials(session_id)
    
    spotify_connected = spotify_token is not None
    youtube_connected = youtube_credentials is not None
    
    spotify_user = None
    if spotify_connected:
        try:
            transfer_service.set_spotify_client(spotify_token)
            spotify_user = transfer_service.spotify.current_user()
        except:
            spotify_connected = False
            db_manager.disconnect_service(session_id, 'spotify')
    
    return render_template('index.html', 
                         spotify_connected=spotify_connected,
                         youtube_connected=youtube_connected,
                         spotify_user=spotify_user)

@app.route('/connect/spotify')
def connect_spotify():
    """Initiate Spotify OAuth"""
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        flash('Spotify credentials not configured', 'error')
        return redirect(url_for('index'))
    
    spotify_oauth = get_spotify_oauth()
    auth_url = spotify_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/spotify/callback')
def spotify_callback():
    """Handle Spotify OAuth callback"""
    code = request.args.get('code')
    if not code:
        flash('Spotify authorization failed', 'error')
        return redirect(url_for('index'))
    
    try:
        session_id = get_session_id()
        spotify_oauth = get_spotify_oauth()
        token_info = spotify_oauth.get_access_token(code)
        
        # Get user info
        transfer_service.set_spotify_client(token_info)
        user_info = transfer_service.spotify.current_user()
        
        db_manager.update_spotify_token(session_id, token_info, user_info['id'])
        flash('Successfully connected to Spotify!', 'success')
    except Exception as e:
        logger.error(f"Spotify callback error: {e}")
        flash('Failed to connect to Spotify', 'error')
    
    return redirect(url_for('index'))

@app.route('/connect/youtube')
def connect_youtube():
    """Initiate YouTube OAuth"""
    if not YOUTUBE_CLIENT_ID or not YOUTUBE_CLIENT_SECRET:
        flash('YouTube credentials not configured', 'error')
        return redirect(url_for('index'))
    
    try:
        flow = get_youtube_flow()
        flow.redirect_uri = YOUTUBE_REDIRECT_URI
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true'
        )
        session['youtube_state'] = state
        return redirect(authorization_url)
    except Exception as e:
        logger.error(f"YouTube OAuth error: {e}")
        flash('Failed to initiate YouTube connection', 'error')
        return redirect(url_for('index'))

@app.route('/youtube/callback')
def youtube_callback():
    """Handle YouTube OAuth callback"""
    try:
        session_id = get_session_id()
        flow = get_youtube_flow()
        flow.redirect_uri = YOUTUBE_REDIRECT_URI
        
        # Fetch the authorization response
        authorization_response = request.url
        
        # Fetch token without state validation to avoid scope mismatch issues
        flow.fetch_token(authorization_response=authorization_response)
        
        credentials = flow.credentials
        
        # Store credentials in database
        credentials_data = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes,
            'expiry': credentials.expiry.isoformat() if credentials.expiry else None
        }
        
        db_manager.update_youtube_credentials(session_id, credentials_data)
        flash('Successfully connected to YouTube!', 'success')
    except Exception as e:
        logger.error(f"YouTube callback error: {e}")
        flash('Failed to connect to YouTube', 'error')
    
    return redirect(url_for('index'))

@app.route('/api/fetch-songs')
def fetch_songs():
    """API endpoint to fetch Spotify liked songs"""
    session_id = get_session_id()
    spotify_token = db_manager.get_spotify_token(session_id)
    
    if not spotify_token:
        return jsonify({'error': 'Spotify not connected'}), 401
    
    try:
        if not transfer_service.set_spotify_client(spotify_token):
            return jsonify({'error': 'Failed to initialize Spotify client'}), 500
        
        songs = transfer_service.get_spotify_liked_songs()
        db_manager.store_songs(session_id, songs)
        
        return jsonify({
            'success': True,
            'count': len(songs),
            'songs': songs
        })
        
    except Exception as e:
        logger.error(f"Error fetching songs: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/transfer', methods=['POST'])
def start_transfer():
    """API endpoint to start the transfer process"""
    session_id = get_session_id()
    spotify_token = db_manager.get_spotify_token(session_id)
    youtube_credentials = db_manager.get_youtube_credentials(session_id)
    
    if not spotify_token or not youtube_credentials:
        return jsonify({'error': 'Both services must be connected'}), 401
    
    songs = db_manager.get_songs(session_id)
    if not songs:
        return jsonify({'error': 'No songs fetched. Please fetch songs first.'}), 400
    
    try:
        # Initialize clients
        transfer_service.set_spotify_client(spotify_token)
        
        # Recreate YouTube credentials
        expiry = None
        if youtube_credentials.get('expiry'):
            expiry = datetime.fromisoformat(youtube_credentials['expiry'])
        
        credentials = Credentials(
            token=youtube_credentials['token'],
            refresh_token=youtube_credentials['refresh_token'],
            token_uri=youtube_credentials['token_uri'],
            client_id=youtube_credentials['client_id'],
            client_secret=youtube_credentials['client_secret'],
            scopes=youtube_credentials['scopes'],
            expiry=expiry
        )
        
        # Refresh token if needed
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            # Update database with new token
            youtube_credentials['token'] = credentials.token
            if credentials.expiry:
                youtube_credentials['expiry'] = credentials.expiry.isoformat()
            db_manager.update_youtube_credentials(session_id, youtube_credentials)
        
        transfer_service.set_youtube_client(credentials)
        
        # Get playlist name from request
        data = request.get_json()
        playlist_name = data.get('playlist_name', f"Spotify Liked Songs - {datetime.now().strftime('%Y-%m-%d')}")
        
        # Create YouTube playlist
        playlist_id = transfer_service.create_youtube_playlist(
            playlist_name,
            "Playlist created from Spotify liked songs using Music Transfer App"
        )
        
        # Store transfer in database
        transfer_id = db_manager.create_transfer(session_id, playlist_id, playlist_name, len(songs))
        
        return jsonify({
            'success': True,
            'playlist_id': playlist_id,
            'playlist_name': playlist_name,
            'transfer_id': transfer_id
        })
        
    except Exception as e:
        logger.error(f"Error starting transfer: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/transfer/process', methods=['POST'])
def process_transfer():
    """API endpoint to process individual songs"""
    session_id = get_session_id()
    transfer = db_manager.get_active_transfer(session_id)
    
    if not transfer:
        return jsonify({'error': 'Transfer not initialized'}), 400
    
    songs = db_manager.get_songs(session_id)
    if not songs:
        return jsonify({'error': 'No songs found'}), 400
    
    try:
        current_index = transfer['processed']
        
        if current_index >= len(songs):
            return jsonify({'error': 'All songs processed'}), 400
        
        song = songs[current_index]
        
        # Search for the song on YouTube
        youtube_result = transfer_service.search_youtube_video(song['name'], song['artist'])
        
        status = 'not_found'
        added_to_playlist = False
        
        if youtube_result:
            # Try to add to playlist
            success = transfer_service.add_video_to_playlist(
                transfer['playlist_id'],
                youtube_result['video_id']
            )
            
            if success:
                status = 'success'
                added_to_playlist = True
            else:
                status = 'add_failed'
        
        # Store result in database
        db_manager.add_transfer_result(
            transfer['id'],
            song['db_id'],
            youtube_result,
            status,
            added_to_playlist
        )
        
        # Update transfer progress
        new_processed = current_index + 1
        new_successful = transfer['successful'] + (1 if added_to_playlist else 0)
        new_failed = transfer['failed'] + (0 if added_to_playlist else 1)
        new_status = 'completed' if new_processed >= len(songs) else 'processing'
        
        db_manager.update_transfer_progress(
            transfer['id'],
            processed=new_processed,
            successful=new_successful,
            failed=new_failed,
            status=new_status
        )
        
        result = {
            'song': {
                'id': song['id'],
                'name': song['name'],
                'artist': song['artist'],
                'album': song['album']
            },
            'youtube_match': youtube_result,
            'status': status,
            'added_to_playlist': added_to_playlist
        }
        
        # Add delay to respect API limits
        time.sleep(0.1)
        
        return jsonify({
            'success': True,
            'result': result,
            'progress': {
                'current': new_processed,
                'total': len(songs),
                'successful': new_successful,
                'failed': new_failed,
                'percentage': (new_processed / len(songs)) * 100
            },
            'completed': new_processed >= len(songs)
        })
        
    except Exception as e:
        logger.error(f"Error processing transfer: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/transfer/status')
def transfer_status():
    """Get current transfer status"""
    session_id = get_session_id()
    transfer = db_manager.get_active_transfer(session_id)
    
    if not transfer:
        return jsonify({'error': 'No transfer in progress'}), 404
    
    songs = db_manager.get_songs(session_id)
    results = db_manager.get_transfer_results(transfer['id'])
    
    return jsonify({
        'playlist_id': transfer['playlist_id'],
        'playlist_name': transfer['playlist_name'],
        'progress': {
            'current': transfer['processed'],
            'total': len(songs),
            'successful': transfer['successful'],
            'failed': transfer['failed'],
            'percentage': (transfer['processed'] / len(songs)) * 100 if len(songs) > 0 else 0
        },
        'completed': transfer['status'] == 'completed',
        'results': results
    })

@app.route('/disconnect/<service>')
def disconnect_service(service):
    """Disconnect from a service"""
    session_id = get_session_id()
    
    if service == 'spotify':
        db_manager.disconnect_service(session_id, 'spotify')
        flash('Disconnected from Spotify', 'info')
    elif service == 'youtube':
        db_manager.disconnect_service(session_id, 'youtube')
        flash('Disconnected from YouTube', 'info')
    
    return redirect(url_for('index'))

@app.route('/clear-session')
def clear_session():
    """Clear all session data"""
    session_id = get_session_id()
    db_manager.clear_session_data(session_id)
    session.clear()
    flash('Session cleared', 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Check environment variables
    required_vars = ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET', 'YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file and ensure all required variables are set.")
    else:
        print("🎵 Music Transfer App starting with HTTPS...")
        print("🔒 Open your browser and go to https://127.0.0.1:5000")
        print("⚠️  You may see a security warning - click 'Advanced' and 'Proceed to 127.0.0.1' to continue")
        
        # Run with HTTPS using adhoc SSL context (self-signed certificate)
        app.run(debug=True, host='127.0.0.1', port=5000, ssl_context='adhoc')