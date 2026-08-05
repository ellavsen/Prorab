# Один образ на три процесса: бот, api и share различаются только командой
# запуска (docker-compose.yml). Разные образы означали бы три места, где можно
# забыть обновить зависимость.
#
# Установка обычная, не editable. Это важнее, чем кажется: editable-установка
# читает файлы из исходного дерева, и недостающий package-data так никогда бы
# не обнаружился. Здесь в образ едет ровно то, что объявлено в pyproject.toml —
# см. test_every_runtime_asset_is_declared_as_package_data.

FROM python:3.13-slim AS build

WORKDIR /src

# Зависимости отдельным слоем: они меняются реже кода, и пересборка после
# правки хендлера не должна тянуть pip заново.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -U pip setuptools \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml LICENSE ./
COPY packages/ ./packages/
COPY apps/ ./apps/
# --no-build-isolation: setuptools уже стоит в окружении, и без флага pip полез
# бы за ним в сеть ещё раз. --no-deps: всё, что нужно, закреплено версиями в
# requirements.txt, и pyproject не должен тихо притащить что-то сверх списка.
RUN /opt/venv/bin/pip install --no-cache-dir --no-build-isolation --no-deps .


FROM python:3.13-slim

# Компилятора и заголовков в финальном образе нет: все колёса ставятся на
# стадии build, сюда приезжает готовое окружение.
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# База — на томе, а не в слое образа: слой исчезает при первом же обновлении.
# Путь совпадает с томом из docker-compose.yml.
ENV ESTIMATE_DB_URL=sqlite:////data/estimate.db

RUN useradd --create-home --uid 10001 prorab \
 && mkdir -p /data \
 && chown prorab:prorab /data
USER prorab
WORKDIR /home/prorab

# Значение по умолчанию — самый безобидный из трёх процессов: без базы, без
# секретов. compose задаёт каждому сервису свою команду.
EXPOSE 8001
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]
