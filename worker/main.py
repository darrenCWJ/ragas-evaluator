"""KG Worker Service — handles memory-intensive KG and test set generation."""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    import db.init
    db.init.init_db()
    logging.getLogger("app").info("Worker DB initialised")
    yield


app = FastAPI(title="KG Worker", lifespan=lifespan)

cors_origins = os.environ.get("CORS_ORIGINS", "").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins if o.strip()] or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
