FROM apache/superset:6.1.0

USER root
# The Trino SQLAlchemy dialect (the `trino://` URI). The apache/superset image
# runs from a uv-managed venv at /app/.venv (no pip inside it), so install with
# `uv pip` targeting that venv — a bare `pip` lands in the system Python,
# invisible to Superset (the classic "No module named 'trino'"). Verify at
# build time so a broken image fails here, not at query time.
RUN uv pip install --python /app/.venv/bin/python --no-cache "trino[sqlalchemy]>=0.330" \
 && python -c "import trino; from trino.sqlalchemy.dialect import TrinoDialect; print('trino driver OK', trino.__version__)"

COPY superset_config.py /app/pythonpath/superset_config.py
COPY register_dataset.py /app/register_dataset.py
COPY bootstrap.sh /app/bootstrap.sh
RUN chmod +x /app/bootstrap.sh

USER superset
CMD ["/app/bootstrap.sh"]
