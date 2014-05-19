FROM ubuntu
MAINTAINER Christopher League <league@contrapunctus.net>
RUN apt-get install -y python
ADD server.py /root/
ENV FLOOP not-so-secret
ENV BRUP secret
VOLUME /logs
EXPOSE 8000
CMD /root/server.py
