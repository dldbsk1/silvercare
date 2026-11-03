"""테스트 환경: ENV=test (app import 전에 설정, .env 값보다 우선)"""
import os

os.environ["ENV"] = "test"
