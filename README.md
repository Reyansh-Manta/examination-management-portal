# Examination Management Portal

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)

## Installation

1. Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows (Command Prompt / PowerShell):
```cmd
python -m venv venv
venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Database Setup

Initialize the database and create the default administrator account:

```bash
python3 create_admin.py
```

Default administrator credentials:
- **Email:** `admin@example.com`
- **Password:** `Admin@123`

## Running the Application

Start the Flask server:

```bash
python3 app.py
```

The application runs on port 5001. Open the following URL in your web browser:

```
http://127.0.0.1:5001/
```

To run on a different port, set the `PORT` environment variable:

```bash
PORT=8000 python3 app.py
```
