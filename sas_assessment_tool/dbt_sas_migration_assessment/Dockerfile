FROM python:3.9

ARG DBT_PROFILE_TARGET
ENV DBT_PROFILE_TARGET=${DBT_PROFILE_TARGET}

RUN apt-get update && apt-get install -y git

COPY . /opt/

RUN pip install -r /opt/requirements_snowflake.txt

WORKDIR /opt/

RUN dbt deps
