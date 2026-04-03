build:
	docker buildx build \
		--build-context common=../common \
		-t auth \
		.

run: build
	docker run --rm -p 0.0.0.0:8000:80 \
		-e ROOT_DOMAIN \
		-e SESSION_SECRET \
		-e STORAGE_DIR=/tmp/aeratools \
		-e SENDGRID_API_KEY \
		-e EMAIL_FROM \
		auth
