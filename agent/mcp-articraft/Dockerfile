FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for articraft (CadQuery + VTK)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git git-lfs curl libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install uv

# Clone articraft
RUN git clone --depth 1 https://github.com/mattzh72/articraft.git /opt/articraft

# Install articraft dependencies
WORKDIR /opt/articraft
RUN uv sync

# Install MCP server dependencies
WORKDIR /app
COPY server/pyproject.toml .
COPY server/generator.py .
COPY server/knowledge_base.py .
RUN pip install -e ".[generator]" || pip install mcp[cli] boto3 fastmcp

# Environment
ENV ARTICRAFT_WORKDIR=/opt/articraft
ENV MCP_TRANSPORT=sse
ENV MCP_PORT=8080
ENV AWS_REGION=us-west-2

EXPOSE 8080

# Default: run generator server
CMD ["python", "generator.py"]
