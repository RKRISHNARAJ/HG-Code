
"""Bioman AI Sales Agent - Main Application"""



from fastapi import FastAPI

from fastapi.middleware.gzip import GZipMiddleware

from fastapi.middleware.cors import CORSMiddleware

import logging

from app.config import settings


# from app.api import webhooks, admin, templates, followup
from app.api import webhooks, admin, templates, followup, drip_followup





logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)



app = FastAPI(

    title="Bioman AI Sales Agent",

    version="1.0.0",

    description="WhatsApp AI Sales Agent for Bioman BioSTP"

)



# Middleware

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)



# Include routers

logger.info("Including routers...")

app.include_router(webhooks.router)

app.include_router(admin.router)

app.include_router(templates.router)

app.include_router(followup.router)

app.include_router(drip_followup.router)


logger.info("✅ All routers included")





@app.on_event("startup")

async def startup_event():

    """Start on app startup"""

    logger.info("="*50)

    logger.info("Bioman AI Sales Agent STARTED!")

    logger.info("="*50)





@app.on_event("shutdown")

async def shutdown_event():

    """Stop on app shutdown"""

    logger.info("Bioman AI Sales Agent SHUTTING DOWN...")





@app.get("/")

async def root():

    """Root endpoint"""

    return {

        "app": "Bioman AI Sales Agent",

        "version": "1.0.0",

        "status": "running",

        "endpoints": {

            "health": "/health",

            "webhooks": "/api/v1/webhooks/wati",

            "admin": "/api/v1/admin/",

            "templates": "/api/v1/templates/"

        }

    }





@app.get("/health")

async def health():

    """Health check endpoint"""

    return {

        "status": "healthy",

        "app": "Bioman AI Sales Agent",

        "version": "1.0.0"

    }





if __name__ == "__main__":

    import uvicorn

    uvicorn.run(

        app,

        host="0.0.0.0",

        port=8000,

        reload=False

    )

