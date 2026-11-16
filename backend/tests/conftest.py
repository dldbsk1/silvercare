"""테스트 환경: ENV=test (app import 전에 설정, .env 값보다 우선)"""
import os

os.environ["ENV"] = "test"
os.environ["AI_PROVIDER"] = "mock"  # .env의 real(실제 Gemini 호출)이 테스트에 섞이지 않게
