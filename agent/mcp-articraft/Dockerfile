FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libxrender1 libxmu6 libxi6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir boto3 cadquery

COPY server/bedrock_generator.py /app/bedrock_generator.py

ENV ARTICRAFT_S3_BUCKET=articraft-assets-412381761882
ENV AWS_DEFAULT_REGION=us-west-2

CMD ["python", "/app/bedrock_generator.py"]
