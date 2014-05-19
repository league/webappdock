FROM ubuntu
MAINTAINER Christopher League <league@contrapunctus.net>
RUN apt-get install -y python
RUN apt-get install -y python-psycopg2
ADD server.py /root/
ENV FLOOP not-so-secret
ENV BRUP ??
ENV LINKS postgresql:db
VOLUME /logs
EXPOSE 8000
CMD /root/server.py /logs/access.log
