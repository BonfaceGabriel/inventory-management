# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV TZ=Africa/Nairobi

# Install system dependencies and set timezone
RUN apt-get update && apt-get install -y postgresql-client tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# Copy and set up the entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]

# Expose the port the app runs on
EXPOSE 8000

# Run the application with Daphne (ASGI server for WebSocket support)
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "management.asgi:application"]
