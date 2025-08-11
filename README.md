# urlshortener

## We python and flask-based web tool for shortening urls

#### Installing:

```bash
# Clone the repo
cd /dir/of/choice
git clone https://github.com/CBI-PITT/urlshortener.git

# Create a virtual environment
# This assumes that you have miniconda or anaconda installed
conda create -n urlshortener python=3.12 -y

# Activate environment and install zarr_stores
conda activate urlshortener
pip install -e /dir/of/choice/urlshortener
```

#### Set Custom options:

```bash
# .env.example
# Copy this file to .env and update the values as needed.

# Flask secret key for session cookies (generate with: python -c "import secrets; print(secrets.token_urlsafe(32))")
FLASK_SECRET_KEY=your_flask_secret_here

# Optional: Base URL for shortened links (e.g., https://sho.rt). If empty, uses request.host_url.
BASE_URL=

# Optional: Google Analytics Measurement ID (e.g., G-XXXXXXXXXX). If set, clicks on short links will trigger GA events.
GTAG_ID=

# Path to the JSON file used to store shortened link data.
URL_DB_PATH=url_db.json

# Admin token required to access /admin (choose a long, random string)
ADMIN_TOKEN=change-me
```



#### Run the web app:

```bash
conda activate urlshortener
python /dir/of/choice/urlshortener/urlshortener/app.py

# Access via: http://localhost:5000
```

