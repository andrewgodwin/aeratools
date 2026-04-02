build:
	docker buildx build \
		--build-context common=../common \
		-t myip \
		.

run: build
	docker run --rm -p 0.0.0.0:8000:80 myip
