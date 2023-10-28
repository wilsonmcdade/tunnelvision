# File: s3.py
# TunnelVision s3 API calls
# Written by Steven Greene for CSH audiophiler

import mimetypes
import boto
import boto.s3.connection

def get_file_s3(bucket, file_hash):
    key = bucket.get_key(file_hash)
    # Generates presigned URL that lasts for 60 seconds (1 minute)
    # If streaming begins prior to the time cutoff, s3 will allow
    # for the streaming to continue, uninterrupted.
    return key.generate_url(90, query_auth=True)

def get_file_list(bucket):
    # List all files in the bucket
    return bucket.list()

def get_date_modified(bucket, file_hash):
    # Get date modified for a specific file in the bucket
    date =  bucket.get_key(file_hash).last_modified
    return date[:(date.index(":") - 2)]

def upload_file(bucket, file_hash, f):
    # Create bucket key with filename
    key = bucket.new_key(file_hash)
    # Set content type
    # There is most certainly a better way to do this but w/e
    content_type = mimetypes.guess_type(f.filename)[0]
    # Upload the file
    key.set_contents_from_file(f, headers={"Content-Type": content_type})

def remove_file(bucket, file_hash):
    # Does anybody read these comments
    bucket.delete_key(file_hash)

def get_bucket(s3_url, s3_key, s3_secret, bucket_name):
    # Establish s3 connection through boto
    # Formatting long paramter strings is never fun
    conn = boto.connect_s3(
                aws_access_key_id = s3_key,
                aws_secret_access_key = s3_secret,
                host = s3_url,
                calling_format = boto.s3.connection.OrdinaryCallingFormat())
    # Return the bucket rather than the entire resource
    return conn.lookup(bucket_name)
