FROM python:3.12-slim

WORKDIR /app

COPY --from=common requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=common templates/ templates/
COPY --from=common static/ static/
COPY --from=common single-page-app.py app.py

COPY . .

EXPOSE 80
CMD ["gunicorn", "-b", "0.0.0.0:80", "app:app"]
