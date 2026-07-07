FROM apache/superset:6.1.0

USER root
RUN pip install --no-cache-dir "trino[sqlalchemy]"

COPY superset_config.py /app/pythonpath/superset_config.py
COPY bootstrap.sh /app/bootstrap.sh
RUN chmod +x /app/bootstrap.sh

USER superset
CMD ["/app/bootstrap.sh"]
