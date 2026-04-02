build:
	docker buildx build \
		--build-context common=../common \
		--build-context root=.. \
		-t index \
		.

run: build
	docker run --rm -p 0.0.0.0:8000:80 -e ROOT_DOMAIN=example.com index
