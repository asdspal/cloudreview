# AWS Cost and Operational Best Practices for Infrastructure-as-Code

## Idle and orphaned resources

Risk: Unattached EBS volumes, idle load balancers, and old snapshots silently accrue
charges. Flag and delete them.

- Unattached EBS volumes: costs per GB-month with zero value.
- Idle Application/Network Load Balancers: hourly charge even with no traffic.
- Old EBS/RDS snapshots: storage cost grows unbounded.

## Right-sizing

Risk: Over-provisioned instances waste money. Prefer Graviton (Arm) instances for
better price/performance, and right-size based on real utilization.

Right: choose `m7g`/`c7g` (Graviton) families where the workload allows.

## Instance types and burstable credits

Risk: Burstable `t3`/`t4g` instances can accrue surplus CPU-credit charges under
sustained load. For steady high-CPU workloads use a fixed-performance family.

## S3 lifecycle policies

Risk: Cold data kept in Standard storage costs more than needed. Add lifecycle rules to
transition to Infrequent Access, then Glacier, then expire.

Right (Terraform):
```hcl
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    id     = "archive"
    status = "Enabled"
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    expiration { days = 365 }
  }
}
```

## Tagging

Risk: Untagged resources make cost allocation impossible. Require at least `owner`,
`environment`, and `cost-center` tags; enforce with AWS Config or a tag policy.

Right:
```hcl
locals {
  tags = { owner = "team-payments", environment = "prod", "cost-center" = "1234" }
}
```

## CloudWatch alarms and logging

Risk: Silent failures. Enable CloudTrail (account trail to a locked-down bucket), and
CloudWatch alarms on critical metrics (5xx rate, queue depth, DB connections).

Right (Terraform):
```hcl
resource "aws_cloudtrail" "main" {
  name                          = "org-trail"
  s3_bucket_name                = aws_s3_bucket.logs.id
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true
}
```

## Termination protection on stateful resources

Risk: An accidental `terraform destroy` or stack delete can wipe a database. Set
`deletion_protection` on databases and `termination_protection` on critical stacks.

## Backup and retention

Risk: No backups means no recovery. Enable automated backups with a retention window,
and AWS Backup plans for stateful services.

## Multi-AZ for production databases

Risk: A single-AZ database has a maintenance-failure and AZ-outage risk. Use `multi_az`
for production.
