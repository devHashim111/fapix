from setuptools import setup, find_packages

setup(
    name='Fapix',
    version='0.1.0',
    author='Hashim',
    author_email='devhashim111@gmail.com',
    description='A FastAPI project manager CLI tool like Django',
    packages=find_packages(exclude=["tests", "*.tests", "*.tests.*"]),
    include_package_data=True,
    install_requires=[
        'click>=8.1.3',
        'jinja2>=3.1.2',
        'tortoise-orm>=0.19.2',
        'sqlalchemy>=2.0.0',
        'alembic>=1.11.0',
    ],
    entry_points={
        'console_scripts': [
            'fapix = fapix.core.cli.main:cli',
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Framework :: FastAPI",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
)

