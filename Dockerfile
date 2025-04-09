FROM python:3.13.2-alpine3.21

RUN pip install --upgrade pip wheel

RUN python -m ensurepip --upgrade && \
    pip install setuptools --upgrade

COPY requirements.txt /requirements.txt
RUN pip install -r requirements.txt

COPY . /app
WORKDIR /app

ENTRYPOINT ["python", "app.py"]
