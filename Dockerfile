FROM ubuntu:latest
MAINTAINER Eden Attenborough "eda@e.email"
ENV TZ=Europe/London
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
RUN apt-get update -y
RUN apt-get install -y python3-pip python3-dev build-essential wkhtmltopdf cron gcc libcups2-dev
RUN mkdir githubPrinter
COPY . /githubPrinter
WORKDIR /githubPrinter
RUN pip3 install -r requirements.txt

RUN echo "*/1 * * * * root python3 /githubPrinter/printIssues.py > /proc/1/fd/1 2>/proc/1/fd/2" > /etc/crontab
ENTRYPOINT ["bash"]
CMD ["entrypoint.sh"]