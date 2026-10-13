# syntax=docker/dockerfile:1
# The pipeline steps as container Lambdas, on AWS's Lambda base image. One image; Terraform picks
# the handler per function (lambdas.handlers.prepare / ocr / extract / decide).
#   docker build -f lambdas/Dockerfile -t docflow-pipeline .     (from backend/)

FROM public.ecr.aws/lambda/python:3.12 AS deps
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv export --locked --no-dev --no-hashes --format requirements-txt > /tmp/requirements.txt \
 && uv pip install --system --no-cache --target "${LAMBDA_TASK_ROOT}" -r /tmp/requirements.txt

FROM public.ecr.aws/lambda/python:3.12
COPY --from=deps ${LAMBDA_TASK_ROOT} ${LAMBDA_TASK_ROOT}
COPY config ${LAMBDA_TASK_ROOT}/config
COPY core ${LAMBDA_TASK_ROOT}/core
COPY documents ${LAMBDA_TASK_ROOT}/documents
COPY lambdas ${LAMBDA_TASK_ROOT}/lambdas
COPY pipeline ${LAMBDA_TASK_ROOT}/pipeline
COPY review ${LAMBDA_TASK_ROOT}/review
COPY tenants ${LAMBDA_TASK_ROOT}/tenants
ENV DJANGO_SETTINGS_MODULE=config.settings
CMD ["lambdas.handlers.prepare"]
