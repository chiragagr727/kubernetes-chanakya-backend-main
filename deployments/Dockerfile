# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment varibles
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SETTINGS_MODULE chanakya_backend.settings.development

# Set work directory
WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y gcc
#RUN wget db:5432
COPY ./requirements/ /app/requirements/
RUN pip install -r /app/requirements/req.txt

# Copy project
COPY . /app/
#RUN python manage.py makemigrations
#RUN python manage.py migrate
# Collect static files
RUN python manage.py collectstatic
# Expose port 8000
EXPOSE 8000

# Run gunicorn
CMD ["gunicorn", "chanakya_backend.wsgi:application", "--bind", "0.0.0.0:8000"]
