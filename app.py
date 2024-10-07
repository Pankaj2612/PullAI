
from flask import Flask, jsonify, render_template, redirect, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
import requests
from dotenv import load_dotenv
import google.generativeai as genai
import os

load_dotenv()

app = Flask(__name__)

API_KEY = os.getenv("API_KEY")


app.secret_key = os.urandom(24)


# Configure the SQLAlchemy database URI (SQLite for this example)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


db = SQLAlchemy(app)

# GitHub OAuth App credentials
client_id =  os.getenv("AUTH_GITHUB_ID")
client_secret = os.getenv("AUTH_GITHUB_SECRET")

# GitHub OAuth URLs
authorize_url = "https://github.com/login/oauth/authorize"
token_url = "https://github.com/login/oauth/access_token"
user_api_url = "https://api.github.com/user"
repos_api_url = "https://api.github.com/user/repos"

# Step 1: Define the Token model for SQLAlchemy
class Token(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    github_user_id = db.Column(db.String(100), unique=True, nullable=False)
    access_token = db.Column(db.String(200), nullable=False)

# Create the database tables
with app.app_context():
    db.create_all()


@app.route('/')
def home():
    return render_template('index.html')


# Step 2: Redirect user to GitHub's OAuth authorization page
@app.route('/login')
def login():
    github_auth_url = f"{authorize_url}?client_id={client_id}&redirect_uri={url_for('callback', _external=True)}&scope=repo"
    return redirect(github_auth_url)


@app.route('/callback')
def callback():
    code = request.args.get('code')

    if not code:
        return "Error: No code provided", 400  # Return a 400 Bad Request status code

    # Step 4: Exchange the authorization code for an access token
    token_response = requests.post(
        token_url,
        headers={'Accept': 'application/json'},
        data={
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'redirect_uri': url_for('callback', _external=True)
        }
    )

    if token_response.status_code != 200:
        return f"Error: Failed to obtain access token - {token_response.text}", token_response.status_code

    token_json = token_response.json()
    access_token = token_json.get('access_token')

    if not access_token:
        return "Error: No access token provided", 400

    # Step 5: Get user details from GitHub
    headers = {
        'Authorization': f"Bearer {access_token}",
        'Accept': 'application/json'
    }
    user_response = requests.get(user_api_url, headers=headers)

    if user_response.status_code != 200:
        return f"Error: Failed to fetch user details - {user_response.text}", user_response.status_code

    user_data = user_response.json()
    github_user_id = str(user_data.get('id'))

    if not github_user_id:
        return "Error: No GitHub user ID provided", 400

    # Check if a token for the user already exists
    existing_token = Token.query.filter_by(github_user_id=github_user_id).first()

    if existing_token:
        # Update the existing access token
        existing_token.access_token = access_token
        db.session.commit()  # Commit the update
    else:
        # Store the access token and user ID in the database
        new_token = Token(github_user_id=github_user_id, access_token=access_token)
        db.session.add(new_token)
        db.session.commit()  # Commit the new token

    


 #
    session['access_token'] = access_token


    return redirect(url_for('profile'))

# Step 7: Show the profile page with user information
@app.route('/profile')
def profile():
    # Get the access token from the session
    access_token = session.get('access_token')
    
    if not access_token:
        return redirect(url_for('login'))  # Redirect to login if no access token is found

    headers = {
        'Authorization': f"Bearer {access_token}",
        'Accept': 'application/json'
    }

    # Fetch the user's GitHub profile
    user_response = requests.get(user_api_url, headers=headers)
    
    if user_response.status_code != 200:
        return "Error fetching user data from GitHub. Please try logging in again.", 400
    
    user_data = user_response.json()

    # Fetch the user's GitHub repositories
    repos_response = requests.get(repos_api_url, headers=headers)
    
    if repos_response.status_code != 200:
        return "Error fetching repository data from GitHub.", 400
    
    repos_data = repos_response.json()
    # Structure the user data for the template
    github_user = {
        'login': user_data['login'],
        'avatar_url': user_data['avatar_url'],
        'html_url': user_data['html_url'],
        'name': user_data.get('name', 'N/A'),
        'bio': user_data.get('bio', 'No bio provided'),
        'repos': repos_data  
    }
 
   
    return render_template('profile.html', user=github_user)



@app.route('/create_webhooks', methods=['POST'])
def create_webhooks():
   
    selected_repos = request.form.getlist('selected_repos')
    if not selected_repos:
        return "No repositories selected for webhook creation.", 400

    
    access_token = session['access_token']

    headers = {
        'Authorization': f"Bearer {access_token}",
        'Accept': 'application/vnd.github+json'
    }


    user_response = requests.get(user_api_url, headers=headers)
    if user_response.status_code != 200:
        return "Error fetching user data from GitHub", 400
    user_data = user_response.json()
    owner = user_data['login']

 
    WEBHOOK_PAYLOAD_URL = os.getenv("WEBHOOK_PAYLOAD_URL")  # e.g., 'https://yourserver.com/webhook_handler'

   
    for repo_name in selected_repos:
        url = f"https://api.github.com/repos/{owner}/{repo_name}/hooks"

        payload = {
            "name": "web",
            "active": True,
            "events": ["pull_request"],
            "config": {
                "url": WEBHOOK_PAYLOAD_URL,
                "content_type": "json",
                "insecure_ssl": "0"  # Set to "1" if using self-signed certificates
            }
        }

        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 201:
            print(f"Webhook successfully created for {repo_name}")
        elif response.status_code == 422 and 'hook already exists' in response.text.lower():
            print(f"Webhook already exists for {repo_name}")
        else:
            print(f"Failed to create webhook for {repo_name}: {response.status_code} - {response.text}")

    return render_template('success.html',repo = repo_name)

@app.route('/webhook_handler', methods=['POST'])
def webhook_handler():
    # Parse the JSON payload
    event = request.headers.get('X-GitHub-Event', 'ping')
    if event == 'ping':
        return jsonify({'msg': 'pong'}), 200

    if event == 'pull_request':
        payload = request.json
        action = payload.get('action')
        if action in ['opened', 'synchronize']:
            pr = payload['pull_request']
            pr_number = pr['number']
            pr_url = pr['html_url']
            repo_full_name = pr['base']['repo']['full_name']
   
            owner = repo_full_name.split('/')[0]

       
            access_token = get_access_token("64430912")
            if not access_token:
                app.logger.error(f"No access token found for repository owner: {owner}")
                return "Access token not found for repository", 400

       
            diff_url = pr['url'] + '.diff'
            diff_response = requests.get(diff_url, headers={
                'Authorization': f'token {access_token}',
                'Accept': 'application/vnd.github.v3.diff'
            })

            if diff_response.status_code != 200:
                app.logger.error(f"Failed to fetch diff for PR #{pr_number} in {repo_full_name}")
                return "Failed to fetch PR diff", 400

            diff_content = diff_response.text

    
            review_comment = review_code_with_ai(diff_content)
            print(review_comment)

            if not review_comment:
                app.logger.error(f"Failed to generate review for PR #{pr_number} in {repo_full_name}")
                return "Failed to generate review", 500

            # Post the review comment
            comment_url = pr['comments_url']
            post_comment(comment_url, review_comment)

    return "Webhook processed", 200


def post_comment(comment_url, comment_body):
 
    access_token = get_access_token("64430912")
    headers = {
        'Authorization': f"Bearer {access_token}",
        'Accept': 'application/vnd.github+json'
    }

    data = {
        'body': comment_body
    }

    response = requests.post(comment_url, headers=headers, json=data)

    if response.status_code == 201:
        print("Comment posted successfully.")
    else:
        print(f"Failed to post comment: {response.status_code} - {response.text}")


def get_access_token(github_user_id):
    
    token_record = Token.query.filter_by(github_user_id=github_user_id).first()
    if token_record:
        return token_record.access_token
    return None


def review_code_with_ai(diff_content):
   
    try:
        genai.configure(api_key=API_KEY)

        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"Please review the following Pull Request:\n\n{diff_content}\n\nProvide feedback on best practices, potential issues, and improvements."

        # Generate content using the model
        response = model.generate_content(prompt)

        # Print the generated code review
        return response.text
    except Exception as e:
        print(f"Error while generating AI review: {e}")
        return "Failed to generate AI review comment."

if __name__ == '__main__':
    app.run(debug=True)