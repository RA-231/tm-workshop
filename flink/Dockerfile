# Flink 1.20 LTS with everything needed to read the prepared JSON and write
# Iceberg to Garage (S3).
#
# Version alignment matters here (verified 2026-07):
#   - iceberg-flink-runtime-1.20 : 1.11.0  — same Iceberg version Trino 482 bundles
#   - iceberg-aws-bundle         : S3FileIO + AWS SDK, for writing to Garage
#   - shaded hadoop uber jar     — Iceberg's Flink catalog still wants Hadoop's
#                                  Configuration classes on the classpath, even
#                                  though no data flows through Hadoop
# Flink is pinned to 1.20 because iceberg-flink-runtime only ships builds up to
# Flink 1.20 / 2.0, and 1.20 is the current LTS.
FROM flink:1.20.5-scala_2.12-java17

ARG MAVEN=https://repo1.maven.org/maven2

RUN wget -q -P /opt/flink/lib \
      $MAVEN/org/apache/iceberg/iceberg-flink-runtime-1.20/1.11.0/iceberg-flink-runtime-1.20-1.11.0.jar \
      $MAVEN/org/apache/iceberg/iceberg-aws-bundle/1.11.0/iceberg-aws-bundle-1.11.0.jar \
      $MAVEN/org/apache/flink/flink-shaded-hadoop-2-uber/2.8.3-10.0/flink-shaded-hadoop-2-uber-2.8.3-10.0.jar

COPY sql /opt/flink/sql
