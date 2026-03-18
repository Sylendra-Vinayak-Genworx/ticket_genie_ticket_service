from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def setup_cors(app: FastAPI)-> None:
    app.add_middleware(
    CORSMiddleware,
     allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost",         
        "https://ticketing-genie-frontend-717740758627.us-east1.run.app"
 
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
