# CityBot2

CityBot2 is a Python-based service that provides location-specific information and services. It offers functionalities related to retrieving weather data, maps, and social media integration to publish information on the city you choose and configure.

[![Snyk](https://snyk.io/test/github/ericrosenberg1/CityBot2/badge.svg)](https://snyk.io/test/github/ericrosenberg1/CityBot2)

## Installation

To install CityBot2, follow these steps:

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
