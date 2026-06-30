#!/bin/zsh

# Local Streamlit launcher for a_stock_assistant.
# If your project path changes, edit PROJECT_DIR below.

PROJECT_DIR="/Users/wanghao/Documents/股票"
APP_URL="http://localhost:8501"

cd "$PROJECT_DIR" || {
  echo "Cannot find project directory: $PROJECT_DIR"
  exit 1
}

if [ ! -d ".venv" ]; then
  echo "Missing .venv. Please create and install the project first."
  exit 1
fi

source .venv/bin/activate

echo "Starting local console at $APP_URL"
python scripts/start_streamlit_safe.py --port 8501
