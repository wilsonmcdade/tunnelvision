# File: s3.py
# TunnelVision s3 API calls
# Written by Steven Greene for CSH audiophiler

import mimetypes
import boto
import boto.s3.connection
import boto3

class S3Bucket:

    def __init__(self, name, key, secret, endpoint):
        self.name = name

        self._session = boto3.session.Session()

        self._client = self._session.client(
            service_name='s3',
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            endpoint_url=endpoint,
        )

    # unused
    # def get_file(self, bucket_name, file_hash, new_file_name, key, secret):
    #     with open(new_file_name, "wb") as f:
    #         boto.utils.fetch_file(f"s3://{bucket_name}/{file_hash}", file=f, username=key, password=secret)

    def get_file_s3(self, file_hash):
        key = self._client.get_objects_v2(self.name, file_hash)
        # Generates presigned URL that lasts for 60 seconds (1 minute)
        # If streaming begins prior to the time cutoff, s3 will allow
        # for the streaming to continue, uninterrupted.
        if (key == None):
            print("Failed to fetch {0}".format(file_hash))
            url = "../static/images/csh_tilted.png"
        else:
            url = key.generate_url(90, query_auth=True)
        return url

    def get_file_list(self):
        # List all files in the bucket
        return self._client.list_objects_v2(self.name)

    def get_date_modified(self, file_hash):
        # Get date modified for a specific file in the bucket
        date =  self._client.get_object(self.name, file_hash).get("LastModified")
        # TODO: this may not work with datetime objects
        return date[:(date.index(":") - 2)]

    def upload_file(self, file_hash, f, filename=""):

        file_path = filename if filename != "" else f.filename

        content_type = mimetypes.guess_type(file_path)[0]

        self._client.upload_file(file_path, self.name, file_hash, {"ContentType": content_type})

    def remove_file(self, file_hash):
        # Does anybody read these comments
        # yes
        self._client.delete_object(self.name, file_hash)