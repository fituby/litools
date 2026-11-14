FROM python:3.14.10-alpine3.24

RUN python -m ensurepip --upgrade && \
    pip install setuptools --upgrade

COPY requirements.txt /requirements.txt
RUN pip install -r requirements.txt

COPY . /app
WORKDIR /app

ENTRYPOINT ["python", "app.py"]
