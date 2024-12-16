# CityBot2

CityBot2 is a Python-based app designed to create social media postings for a local area, with the initial version featuring news source RSS feeds and government-sourced data on weather, and earthquakes. It supports postings to Bluesky, Facebook, LinkedIn, Reddit, and Twitter/X.

You can download it to your server and schedule it to run with customizations for your city. I'd love your help testing and improving!

This is a major upgrade and full rewrite of my original [CityBot](https://github.com/ericrosenberg1/CityBot).

[![Snyk](https://snyk.io/test/github/ericrosenberg1/CityBot2/badge.svg)](https://snyk.io/test/github/ericrosenberg1/CityBot2)
[![Maintainability](https://api.codeclimate.com/v1/badges/4857f450946330748975/maintainability)](https://codeclimate.com/github/ericrosenberg1/CityBot2/maintainability)
[![Test Coverage](https://api.codeclimate.com/v1/badges/4857f450946330748975/test_coverage)](https://codeclimate.com/github/ericrosenberg1/CityBot2/test_coverage)

## Installation

To install CityBot2, clone the repository to your system, then follow these steps:

1. Edit configuration files:
   - `nano config/credentials.env`
   - `nano config/social_config.json`

2. Start the service:
   - `sudo systemctl start citybot`

3. Enable service at boot:
   - `sudo systemctl enable citybot`

4. Check service status:
   - `sudo systemctl status citybot`

5. View logs:
   - `tail -f logs/citybot.log`

## Dependencies

CityBot2 requires the following dependencies:
- python3-pip
- python3-dev
- build-essential
- libatlas-base-dev
- gfortran
- libgeos-dev
- libproj-dev
- proj-data
- proj-bin
- libcairo2-dev
- pkg-config
- python3-cartopy
- cutycapt

## Usage

CityBot2 can be utilized to retrieve city-specific information. An example of usage is as follows:

```bash
python3 citybot.py
```

This command will start the bot for the default city "ventura." You can specify a different city by setting the `CITYBOT_CITY` environment variable.

## Authors

CityBot2 was created by me, @EricRosenberg1.

## Contributing

Contributions to CityBot2 are welcome! If you encounter any bugs or issues, please report them by opening an issue [here](https://github.com/ericrosenberg1/CityBot2/issues).

For making contributions via pull requests (PR), follow these steps:
1. Fork the repository.
2. Create a new branch (`git checkout -b feature/your-branch-name`).
3. Make your changes.
4. Commit your changes (`git commit -am 'Add new feature'`).
5. Push to the branch (`git push origin feature/your-branch-name`).
6. Create a new Pull Request.

For support or inquiries about commercial support, please contact [Author Name] via email.

## Additional Information

For more details on the functionalities and capabilities of CityBot2, refer to the source code and documentation provided in the repository. Feel free to explore and enhance the service for your specific needs. 🌟

## Thanks

*The initial version of this readme was created using the  project [GPT4Readability](https://github.com/loevlie/GPT4Readability)
*Much of the initial code was created using Claude.ai
