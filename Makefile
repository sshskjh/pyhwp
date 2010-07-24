test:
	python tests.py
archive:
	git archive --format=tar HEAD | gzip -9 > hwp-HEAD.tar.gz
publish: publishhost publishdir
	git archive --format=tar HEAD | gzip -9 | ssh `cat publishhost` "cd `cat publishdir`; tar xz"
publishhost:
	cat > publishhost
publishdir:
	cat > publishdir