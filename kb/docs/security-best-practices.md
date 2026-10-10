# AWS Security Best Practices for Infrastructure-as-Code

Rules for reviewing Terraform, CloudFormation, CDK, and AWS CLI. Each rule states the
risk and gives a correct fix. "Wrong" shows a common mistake; "Right" shows the fix.

## S3 bucket public access

Risk: A bucket with a public ACL or public policy can leak data to the internet. The
modern, reliable fix is a SEPARATE `aws_s3_bucket_public_access_block` resource, not
attributes on the bucket resource.

Wrong (Terraform):
```hcl
resource "aws_s3_bucket_acl" "data" {
  bucket = aws_s3_bucket.data.id
  acl    = "public-read"
}
```

Right (Terraform):
```hcl
resource "aws_s3_bucket" "data" {
  bucket = "my-data"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

Note: `block_public_acls` and friends are NOT arguments of `aws_s3_bucket`; they belong
to `aws_s3_bucket_public_access_block`.

## S3 encryption at rest

Risk: Without default encryption, objects are stored unencrypted.

Right (Terraform):
```hcl
resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true
  }
}
```

## S3 versioning

Risk: Without versioning, overwritten or deleted objects cannot be recovered.

Right (Terraform):
```hcl
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}
```

## IAM wildcard permissions

Risk: `Action: "*"` plus `Resource: "*"` grants full admin. A leaked key means full
account compromise. Scope actions and resources to the minimum required.

Wrong:
```json
{ "Effect": "Allow", "Action": "*", "Resource": "*" }
```

Right:
```json
{ "Effect": "Allow", "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::my-data/*"] }
```

## Root account and MFA

Risk: Access keys on the root user are a top account-takeover vector. Root access keys
should not exist; root should have MFA and no programmatic access. Use IAM roles or
users for programmatic access.

## IAM policy condition operators

Risk: `ForAnyValue:StringLike` / `ForAllValues:StringLike` evaluate to true when the
condition key is absent (for ForAllValues, an empty set is vacuously true), so a missing
tag can accidentally ALLOW a request. Always pair with a `Null` check.

Right:
```json
"Condition": {
  "Null": { "aws:PrincipalTag/team": "false" },
  "StringEquals": { "aws:PrincipalTag/team": "payments" }
}
```

## Public security groups

Risk: `0.0.0.0/0` on ports 22 or 3389 exposes SSH/RDP to the internet and invites brute
force. Restrict to known CIDRs or use Systems Manager Session Manager instead of SSH.

Wrong:
```hcl
ingress { from_port = 22, to_port = 22, protocol = "tcp", cidr_blocks = ["0.0.0.0/0"] }
```

Right: restrict `cidr_blocks` to your VPN/bastion range, or remove SSH entirely and use
SSM Session Manager.

## RDS encryption and public access

Risk: `publicly_accessible = true` and unencrypted storage expose the database.

Right (Terraform):
```hcl
resource "aws_db_instance" "db" {
  storage_encrypted   = true
  kms_key_id          = aws_kms_key.data.arn
  publicly_accessible = false
  multi_az            = true
  deletion_protection = true
}
```

## EBS encryption

Risk: Unencrypted volumes can be read if a snapshot leaks. Enable account-level EBS
encryption by default so every new volume is encrypted.

## Least-privilege trust policies (confused deputy)

Risk: Service roles that can be assumed by a service principal without a source
condition can be assumed by other accounts' resources (confused deputy). Add
`aws:SourceAccount` and `aws:SourceArn` conditions.

Right:
```json
"Condition": {
  "StringEquals": { "aws:SourceAccount": "123456789012" },
  "ArnLike": { "aws:SourceArn": "arn:aws:s3:::my-bucket" }
}
```
