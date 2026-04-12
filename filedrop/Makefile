build:
	docker buildx build --build-context common=../common -t filedrop .

run: build
	docker run --rm -p 0.0.0.0:8000:80 \
	  -e SESSION_SECRET=dev \
	  -e STORAGE_DIR=/tmp/storage \
	  -e ROOT_DOMAIN=localhost:8000 \
	  filedrop
