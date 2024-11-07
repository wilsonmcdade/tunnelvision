# Tunnelvision - An interactive catalog of RIT's Murals

## Running Locally
(Reach out to a maintainer of this repo for credentials for the dev database)
* Fork the repo and run the following commands in that directory:
* `python3 -m venv venv`
* `source venv/bin/activate`
* `pip3 install -r requirements.txt`
* `python3 app.py`



## Docker Infrastructure:
The docker compose config in this repository is intended to provide a small/simple suite of services for TunnelVision to rely on. This is for development and testing purposes.

To use this suite:

1. create a file called `compose.env` in the root of the repository. Use the following template to get started:

```
MINIO_ROOT_USER=
MINIO_ROOT_PASSWORD=
POSTGRES_USER=
POSTGRES_PASSWORD=
```
2. fill in appropriate values
3. `docker compose up`
4. navigate to http://localhost:9001, log in with the root credentials for minio specified above, add create a bucket for TunnelVision
5. while still in the minio console, navigate to "access keys" on the left and create an access key and secret for tunnelvision to use.
6. Provide the the information to TunnelVision
   - S3 url: `http://localhost:9000`
   - the s3 secret and key you generated
   - S3 bucket name: whatever you created
   - database host: `localhost`
   - DB user and password: whatever you set in `compose.env` for postgres
   - DB name: should match the db user by default