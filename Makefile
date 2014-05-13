CFLAGS=-Wall

default: sudo-deploy
	chown root sudo-deploy
	chmod u+s sudo-deploy
