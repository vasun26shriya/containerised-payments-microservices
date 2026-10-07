FROM python:3.13.16-slim-trixie@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt && python -m pip uninstall -y pip
COPY services /app/services
USER 10001
EXPOSE 8000
CMD ["uvicorn", "services.payments:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
