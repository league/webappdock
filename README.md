webappdock
==========

Deploy and manage web applications as docker containers.

````
usage: webappdock.py [-h] [-V] {config,init,make,deploy,clean,list,test} ...

deploy and manage web applications as docker containers

optional arguments:
  -h, --help            show this help message and exit
  -V, --version         show program's version number and exit

Commands:
  {config,init,make,deploy,clean,list,test}
    config              ensure all dependencies are installed and ready♯
    init                create bare repository, ready for git push
    make                build a docker image and run in a new container
    deploy              expose a running container as a host site♯
    clean               stop and remove old containers and images♮
    list                show details about previous builds and deployments
    test                run test cases

  ♯ requires root privilege   ♮ can do more if given root privilege
````
