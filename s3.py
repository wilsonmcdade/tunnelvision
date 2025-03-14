# File: s3.py
# TunnelVision s3 API calls
# Written by Steven Greene for CSH audiophiler

import mimetypes
import boto3


class S3Bucket:

    def __init__(self, name, key, secret, endpoint):
        self.name = name

        self._session = boto3.session.Session()

        self._client = self._session.client(
            service_name="s3",
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            endpoint_url=endpoint,
        )

    def get_file(self, file_hash, download_to):
        """Download the file to the specified path"""
        with open(download_to, "wb") as f:
            self._client.download_fileobj(self.name, file_hash, f)

    def get_file_s3(self, file_hash):
        """Get the path to the file specified by file_hash"""
        # Generates presigned URL that lasts for 60 seconds (1 minute)
        # If streaming begins prior to the time cutoff, s3 will allow
        # for the streaming to continue, uninterrupted.
        if file_hash is None:
            print(f"Failed to fetch {file_hash}")
            url = "../static/images/csh_tilted.png"
        else:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.name, "Key": file_hash},
                ExpiresIn=90,
            )

        return url

    # def get_date_modified(self, file_hash):
    #     # Get date modified for a specific file in the bucket
    #     date =  self._client.get_object(self.name, file_hash).get("LastModified")
    #     # TODO: this may not work with datetime objects
    #     return date[:(date.index(":") - 2)]

    def upload_file(self, file_hash:str, f, filename=""):
        """Uploads a file from the provided file object to s3

        Args:
            file_hash (str): the hash of the file to use for the filename
            f (a file-like object): the file-like object to upload
            filename (str, optional): the filename of the file to upload. Defaults to "", which auto-detects the name.
        """
        # Set content type
        # There is most certainly a better way to do this but w/e
        if filename == "":
            filename = f.filename

        content_type = mimetypes.guess_type(filename)[0]
        # Upload the file
        self._client.upload_fileobj(
            f, self.name, file_hash, ExtraArgs={"ContentType": content_type}
        )

    def remove_file(self, file_hash):
        # Does anybody read these comments
        # yes
        self._client.delete_object(Bucket=self.name, Key=file_hash)
