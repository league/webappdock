FROM ubuntu
MAINTAINER Christopher League <league@contrapunctus.net>
RUN apt-get install -y nginx
RUN echo "daemon off;" >>/etc/nginx/nginx.conf
RUN echo ok >/usr/share/nginx/html/ping
EXPOSE 80
CMD /usr/sbin/nginx
