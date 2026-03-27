FROM python:3.11-slim

WORKDIR /app

# install uv
RUN pip install --no-cache-dir uv

# copy dependency files
COPY requirements.txt .

# install dependencies using uv (faster than pip)
RUN uv pip install --system --no-cache -r requirements.txt

# copy app code
COPY . .

# run app
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]