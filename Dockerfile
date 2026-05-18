FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY resume_screener_backend ./resume_screener_backend
COPY 简历筛选器_MVP原型.html ./简历筛选器_MVP原型.html

RUN mkdir -p /app/data

EXPOSE 8765

CMD ["python", "resume_screener_backend/app.py"]
