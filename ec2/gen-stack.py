import base64
import io
import os
import subprocess
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 1. pack the app code
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tar:
    for f in ("agent.py", "app.py"):
        tar.add(os.path.join(ROOT, f), arcname=f)
app_b64 = base64.b64encode(buf.getvalue()).decode()

AMI = subprocess.run(
    ["aws", "ec2", "describe-images", "--owners", "amazon", "--region", "us-west-2",
     "--filters", "Name=name,Values=al2023-ami-2023.*-x86_64", "Name=state,Values=available",
     "--query", "sort_by(Images,&CreationDate)[-1].ImageId", "--output", "text"],
    capture_output=True, text=True).stdout.strip()

TEMPLATE = f"""AWSTemplateFormatVersion: '2010-09-09'
Description: CloudReview - Streamlit IaC-review agent on a free-tier EC2 instance

Parameters:
  InstanceType:
    Type: String
    Default: t3.micro
  AmiId:
    Type: AWS::EC2::Image::Id
    Default: {AMI}
  KeyName:
    Type: AWS::EC2::KeyPair::KeyName
    Default: ashwini-oregon

Resources:
  Vpc:
    Type: AWS::EC2::VPC
    Properties:
      CidrBlock: 10.0.0.0/16
      EnableDnsSupport: true
      EnableDnsHostnames: true
      Tags: [{{Key: Name, Value: cloudreview-vpc}}]

  Subnet:
    Type: AWS::EC2::Subnet
    Properties:
      VpcId: !Ref Vpc
      CidrBlock: 10.0.0.0/24
      MapPublicIpOnLaunch: true
      AvailabilityZone: !Select [0, !GetAZs '']

  Igw:
    Type: AWS::EC2::InternetGateway
    Properties:
      Tags: [{{Key: Name, Value: cloudreview-igw}}]

  IgwAttach:
    Type: AWS::EC2::VPCGatewayAttachment
    Properties:
      VpcId: !Ref Vpc
      InternetGatewayId: !Ref Igw

  RouteTable:
    Type: AWS::EC2::RouteTable
    Properties:
      VpcId: !Ref Vpc

  DefaultRoute:
    Type: AWS::EC2::Route
    DependsOn: IgwAttach
    Properties:
      RouteTableId: !Ref RouteTable
      DestinationCidrBlock: 0.0.0.0/0
      GatewayId: !Ref Igw

  SubnetRouteAssoc:
    Type: AWS::EC2::SubnetRouteTableAssociation
    Properties:
      SubnetId: !Ref Subnet
      RouteTableId: !Ref RouteTable

  InstanceRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal: {{Service: ec2.amazonaws.com}}
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
      Policies:
        - PolicyName: bedrock-review
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action: [bedrock:InvokeModel, bedrock:InvokeModelWithResponseStream]
                Resource:
                  - !Sub arn:aws:bedrock:${{AWS::Region}}:${{AWS::AccountId}}:inference-profile/us.amazon.nova-micro-v1:0
                  - arn:aws:bedrock:*::foundation-model/amazon.nova-micro-v1:0
              - Effect: Allow
                Action: [bedrock:Retrieve, bedrock:RetrieveAndGenerate]
                Resource: !Sub arn:aws:bedrock:${{AWS::Region}}:${{AWS::AccountId}}:knowledge-base/BF2T5CZDI5
              - Effect: Allow
                Action: [bedrock:GetKnowledgeBase, bedrock:ListKnowledgeBases]
                Resource: '*'

  InstanceProfile:
    Type: AWS::IAM::InstanceProfile
    Properties:
      Roles: [!Ref InstanceRole]

  SecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: CloudReview public web
      VpcId: !Ref Vpc
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 8501
          ToPort: 8501
          CidrIp: 0.0.0.0/0
          Description: public Streamlit (demo only)

  Instance:
    Type: AWS::EC2::Instance
    Properties:
      ImageId: !Ref AmiId
      InstanceType: !Ref InstanceType
      KeyName: !Ref KeyName
      IamInstanceProfile: !Ref InstanceProfile
      SubnetId: !Ref Subnet
      SecurityGroupIds: [!Ref SecurityGroup]
      Tags: [{{Key: Name, Value: cloudreview}}]
      UserData:
        Fn::Base64: !Sub |
          #!/bin/bash
          set -euxo pipefail
          dnf install -y python3-pip
          mkdir -p /opt/cloudreview
          python3 -m venv /opt/cloudreview/venv
          /opt/cloudreview/venv/bin/pip install --quiet --upgrade pip
          /opt/cloudreview/venv/bin/pip install --quiet streamlit boto3
          echo '{app_b64}' | base64 -d | tar xz -C /opt/cloudreview
          cat >/etc/systemd/system/cloudreview.service <<'UNIT'
          [Unit]
          Description=CloudReview Streamlit
          After=network-online.target
          [Service]
          WorkingDirectory=/opt/cloudreview
          Environment=AWS_REGION=us-west-2
          ExecStart=/opt/cloudreview/venv/bin/streamlit run app.py --server.headless true --server.port 8501 --server.address 0.0.0.0
          Restart=always
          User=ec2-user
          [Install]
          WantedBy=multi-user.target
          UNIT
          systemctl daemon-reload
          systemctl enable --now cloudreview

  ElasticIp:
    Type: AWS::EC2::EIP
    Properties:
      Domain: vpc
      InstanceId: !Ref Instance

Outputs:
  InstanceId:
    Value: !Ref Instance
  PublicIp:
    Value: !Ref ElasticIp
  Url:
    Value: !Sub http://${{ElasticIp.PublicIp}}:8501
"""

with open(os.path.join(HERE, "cloudreview.yml"), "w") as f:
    f.write(TEMPLATE)

print("AMI:", AMI)
print("app b64 bytes:", len(app_b64))
print("template bytes:", len(TEMPLATE))
