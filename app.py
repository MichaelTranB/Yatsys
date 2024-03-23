import os
import numpy as np
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room
from google.cloud import vision
from google.oauth2.service_account import Credentials as GoogleCredentials
from flask_cors import CORS
from PIL import Image
import cv2
import io
import base64
from firebase_admin import credentials as FirebaseCredentials, initialize_app, db, storage
from werkzeug.utils import secure_filename
import requests
from io import BytesIO
import tensorflow as tf
from tensorflow.keras import datasets, layers, models

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'placeholder_secret_key')
SCOPES = ['https://www.googleapis.com/auth/classroom.courses.readonly']
google_credentials = GoogleCredentials.from_service_account_file(
    os.getenv('GOOGLE_CREDENTIALS_PATH', 'path/to/my/google/credentials.json')
)
client = vision.ImageAnnotatorClient(credentials=google_credentials)
socketio = SocketIO(app)
cors = CORS(app, origins='*')

firebase_credentials = FirebaseCredentials.Certificate(
    os.getenv('FIREBASE_CREDENTIALS_PATH', 'path/to/my/firebase/credentials.json')
)

try:
    firebase_app = initialize_app(firebase_credentials, {
        'databaseURL': os.getenv('FIREBASE_DATABASE_URL', 'placeholder_firebase_database_url'),
        'storageBucket': os.getenv('FIREBASE_STORAGE_BUCKET', 'placeholder_firebase_storage_bucket')
    })
except ValueError:
    # If the app is already initialized, get the existing app
    firebase_app = initialize_app.get_app()
@app.route('/webcam')
def index():
    return render_template('webcam.html')
@app.route('/training')
def training():
    ref = db.reference('profiles')
    profiles = ref.get()
    if not profiles:
        profiles = []
    return render_template('training.html', profiles=profiles)
@app.route('/create_profile', methods=['POST'])
def create_profile():
    profile_name = request.form.get('name')
    if not profile_name or len(profile_name) < 1:
        return jsonify(success=False, message="Profile name is required."), 400
    try:
        ref = db.reference('profiles')
        ref.child(profile_name).set({'name': profile_name})
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500
    return jsonify(success=True)
@app.route('/profile/<profile_name>')
def profile(profile_name):
    ref = db.reference(f'profiles/{profile_name}')
    profile = ref.get()
    if profile is None:
        return render_template('training.html', error="Profile not found.")
    images = {}
    labels = {}
    if profile is not None:
        for emotion in profile.keys():
            if emotion != 'name':  # name is not an emotion
                images[emotion] = []
                labels[emotion] = []
                for filename, details in profile[emotion].items():
                    images[emotion].append(details['url'])
                    labels[emotion].append(emotion)
    return jsonify(profile=profile, images=images, labels=labels)
@app.route('/upload', methods=['POST'])
def upload():
    filenames = []
    urls = []
    if 'image' not in request.files or 'emotion' not in request.form:
        return jsonify({'error': 'No file or emotion found'}), 400
    files = request.files.getlist('image')
    emotion = request.form['emotion']
    profile_name = request.form['profile_name']
    if files and emotion and profile_name:
        for file in files:
            if file.filename == '':
                continue
            filename = secure_filename(file.filename)
            print(f'Saving file: {filename}')  # Log the filename
            file.save(filename)
            # Specify your bucket name
            bucket = storage.bucket()
            # Specify the path to the image in Firebase Storage
            path_to_image = f'{profile_name}/{emotion}/{filename}'
            # Create a blob object representing the image
            blob = bucket.blob(path_to_image)
            # Set the blob to have a public read access
            blob.upload_from_filename(filename, predefined_acl='publicRead')
            # Generate the public URL for the image
            url = blob.public_url
            print(f'File uploaded: {filename}')  # Log the successful upload
            urls.append(url)
            filename_without_ext = os.path.splitext(filename)[0]  # Remove file extension
            ref = db.reference(f'profiles/{profile_name}/{emotion}/{filename_without_ext}')  # Use filename without extension
            ref.set({'emotion': emotion, 'url': url})
            filenames.append(filename)
            os.remove(filename)
    return jsonify({'message': 'Files and emotion successfully uploaded', 'filenames': filenames, 'urls': urls}), 200
@app.route('/delete_image', methods=['POST'])
def delete_image():
    profile_name = request.form['profile_name']
    image_url = request.form['image_url']
    # Parse image_url to get blob name
    blob_name = '/'.join(image_url.split('/')[4:])
    # Remove the image from Firebase Realtime Database
    ref = db.reference('profiles')
    profile_ref = ref.child(profile_name)
    # Searching each emotion for the image
    for emotion in profile_ref.get().keys():
        if emotion != 'name':  # name is not an emotion
            images_ref = profile_ref.child(emotion)
            for image_key, image_val in images_ref.get().items():
                if image_val['url'] == image_url:
                    images_ref.child(image_key).delete()  # Delete the image
    # Remove the image from Google Cloud Storage
    bucket = storage.bucket()
    blob = bucket.blob(blob_name)
    blob.delete()
    return jsonify(success=True)
@app.route('/update_image', methods=['POST'])
def update_image():
    profile_name = request.form['profile_name']
    image_url = request.form['image_url']
    new_emotion = request.form['new_emotion']
    # Parse image_url to get blob name and filename
    blob_name = '/'.join(image_url.split('/')[4:])
    filename = blob_name.split('/')[-1]
    # Find the image in Firebase Realtime Database and delete it
    ref = db.reference('profiles')
    profile_ref = ref.child(profile_name)
    old_emotion = None
    old_image_key = None
    for emotion in profile_ref.get().keys():
        if emotion != 'name':  # name is not an emotion
            images_ref = profile_ref.child(emotion)
            for image_key, image_val in images_ref.get().items():
                if image_val['url'] == image_url:
                    old_emotion = emotion
                    old_image_key = image_key
                    images_ref.child(image_key).delete()  # Delete the old image
                    break  # No need to check other images
            if old_image_key is not None:
                break  # No need to check other emotions
    # Move the blob in Google Cloud Storage to the new emotion folder
    if old_emotion is not None:
        bucket = storage.bucket()
        old_blob = bucket.blob(blob_name)
        new_blob = bucket.blob(f'{profile_name}/{new_emotion}/{filename}')
        bucket.copy_blob(old_blob, bucket, new_blob_name=new_blob.name)  # Copy the blob
        old_blob.delete()  # Delete the old blob
        new_url = f"https://storage.googleapis.com/{bucket.name}/{new_blob.name}"
        # Add the new image to the new emotion in Firebase Realtime Database
        new_images_ref = profile_ref.child(new_emotion)
        new_images_ref.push({'emotion': new_emotion, 'url': new_url})
    return jsonify(success=True)

@app.route('/get_model', methods=['GET'])
def get_model():
    profile_name = request.args.get('profile_name')
    model_path = f'models/{profile_name}.h5'
    if os.path.exists(model_path):
        return send_from_directory('models', f'{profile_name}.h5')
    else:
        return jsonify({'error': 'Model not found'}), 404

@app.route('/train', methods=['GET'])
def train():
    profile_name = request.args.get('profile_name')
    # Call your training function here
    train_model(profile_name)
    return jsonify({'message': 'Model trained successfully'}), 200

@socketio.on('connect')
def test_connect():
    print('Client connected')

@socketio.on('video_feed')
def video_feed(binary_data):
    # Decode the base64-encoded video data
    nparr = np.frombuffer(base64.b64decode(binary_data), np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    image = Image.fromarray(image)
    image.save('temp.jpg', 'JPEG')
    with io.open('temp.jpg', 'rb') as image_file:
        content = image_file.read()

    # Perform face detection
    image = vision.Image(content=content)
    response = client.face_detection(image=image)
    faces = response.face_annotations

    dominant_emotion = "No emotion detected"
    for face in faces:
        emotions = {}
        if face.joy_likelihood != vision.Likelihood.UNKNOWN:
            emotions['joy'] = face.joy_likelihood
        if face.sorrow_likelihood != vision.Likelihood.UNKNOWN:
            emotions['sorrow'] = face.sorrow_likelihood
        if face.anger_likelihood != vision.Likelihood.UNKNOWN:
            emotions['anger'] = face.anger_likelihood
        if face.surprise_likelihood != vision.Likelihood.UNKNOWN:
            emotions['surprise'] = face.surprise_likelihood
        if face.under_exposed_likelihood != vision.Likelihood.UNKNOWN:
            emotions['under_exposed'] = face.under_exposed_likelihood

        if emotions:
            dominant_emotion = max(emotions, key=emotions.get)

    emit('emotion_result', {'result': dominant_emotion})

@socketio.on('create')
def on_create_or_join(room):
    print('create room', room)
    room = room.strip()
    num_clients=0
    # my_room = socketio.server.manager.rooms.get(room) or {'size': 0}
    print(room, '  has', num_clients, 'clients')
    if num_clients == 0:
        join_room(room)
        emit('created', room, room=room)
    elif num_clients == 1:
        join_room(room)
        emit('joined', room, room=room)
    else:
        emit('full', room, room=room)

@socketio.on('join')
def on_join(room):
    print('join room', room)
    room = room.strip()
    join_room(room)
    emit('joined', room, room=room)

@socketio.on('ready')
def on_ready(room):
    emit('ready', room, room=room, broadcast=True)

@socketio.on('candidate')
def on_candidate(event):
    print("------candidate ----")
    emit('candidate', event, room=event['room'], broadcast=True)

@socketio.on('offer')
def on_offer(event):
    print("------offer ----")
    emit('offer', event['sdp'], room=event['room'], broadcast=True)

@socketio.on('answer')
def on_answer(event):
    print("------answer ----")
    emit('answer', event['sdp'], room=event['room'], broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8000, debug=True)