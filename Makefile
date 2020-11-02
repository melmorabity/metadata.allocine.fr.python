ADDON_ID = $(shell xmllint -xpath "string(/addon/@id)" addon.xml)
VERSION = $(shell xmllint -xpath "string(/addon/@version)" addon.xml)

PYTHON_FILES = addon.py $(shell find resources/ -name "*.py")
PLAYLIST_FILE = resources/bouyguestv.m3u8
ASSET_FILES = resources/icon.png resources/fanart.jpg
LANGUAGE_FILES = $(wildcard resources/language/*/strings.po)
DOC_FILES = README.md LICENSE
ADDON_FILES = addon.xml resources/settings.xml $(PYTHON_FILES) $(ASSET_FILES) $(LANGUAGE_FILES) $(DOC_FILES)
ADDON_PACKAGE_FILE = $(ADDON_ID)-$(VERSION).zip

ICON_SIZE = 512
FANART_WIDTH = 1280

KODI_ADDON_DIR = $(HOME)/.kodi/addons
KODI_BRANCH = leia

GITHUB_TOKEN = $(shell cat .githubtoken)
GITHUB_REPOSITORY = melmorabity/$(ADDON_ID)


all: package


resources/icon.png: resources/icon.svg
	rsvg-convert $< -w $(ICON_SIZE) -f png -o $@


resources/fanart.jpg: resources/fanart.svg
	rsvg-convert $< -w $(FANART_WIDTH) -f png | convert - $@


$(ADDON_PACKAGE_FILE): $(ADDON_FILES)
	ln -s . $(ADDON_ID)
	zip -FSr $@ $(foreach f,$^,$(ADDON_ID)/$(f))
	$(RM) $(ADDON_ID)


package: $(ADDON_PACKAGE_FILE)


install: $(ADDON_PACKAGE_FILE)
	unzip -o $< -d $(KODI_ADDON_DIR)


uninstall:
	$(RM) -r $(KODI_ADDON_DIR)/$(ADDON_ID)/


lint:
	flake8 $(PYTHON_FILES)
	pylint $(PYTHON_FILES)
	mypy $(PYTHON_FILES)
	bandit $(PYTHON_FILES)


check: $(ADDON_PACKAGE_FILE)
	$(eval TEMP_DIR := $(shell mktemp -d -p /var/tmp))
	unzip -o $< -d $(TEMP_DIR)
	kodi-addon-checker --branch $(KODI_BRANCH) $(TEMP_DIR)
	$(RM) -r $(TEMP_DIR)


tag: lint check
	git tag $(VERSION)
	git push origin $(VERSION)


clean:
	$(RM) $(ADDON_PACKAGE_FILE)
	$(RM) $(shell find . -name "*~")


mrproper: clean
	$(RM) resources/{icon.png,fanart.jpg}


.PHONY: package install uninstall lint check tag clean mrproper
