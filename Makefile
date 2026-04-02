TOOLS = clock dashboard text weather-header

build:
	@for tool in $(TOOLS); do \
		$(MAKE) -C $$tool build; \
	done

push: build
	@if [ -z "$(PREFIX)" ]; then echo "Usage: make push PREFIX=registry.example.com/"; exit 1; fi
	@for tool in $(TOOLS); do \
		docker tag $$tool $(PREFIX)$$tool && \
		docker push $(PREFIX)$$tool; \
	done
