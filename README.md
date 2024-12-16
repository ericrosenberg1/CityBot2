<a id="readme-top"></a>
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]

<h3 align="center">CityBot2</h3>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href='dependencies'>Dependencies</a></li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#contributors">Contributors</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

## About The Project
CityBot2 is a Python-based app designed to create social media posts for a local area. The initial version features news source RSS feeds and government-sourced data on weather and earthquakes. It supports Bluesky, Facebook, LinkedIn, Reddit, and Twitter/X.

You can download it to your server and schedule it to run with customizations for your city. I'd love your help testing and improving!

This is a major upgrade and full rewrite of my original (archived) [CityBot](https://github.com/ericrosenberg1/CityBot).

[![Snyk](https://snyk.io/test/github/ericrosenberg1/CityBot2/badge.svg)](https://snyk.io/test/github/ericrosenberg1/CityBot2)
[![Maintainability](https://api.codeclimate.com/v1/badges/4857f450946330748975/maintainability)](https://codeclimate.com/github/ericrosenberg1/CityBot2/maintainability)
[![Test Coverage](https://api.codeclimate.com/v1/badges/4857f450946330748975/test_coverage)](https://codeclimate.com/github/ericrosenberg1/CityBot2/test_coverage)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/efb5beefe547465087883828710a7a11)](https://app.codacy.com/gh/ericrosenberg1/CityBot2/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With
* [Python][Python]][Python-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started
This app comes with no warranties or guarantees. Use it at your own risk. I suggest using a virtual environment to segregate the files and dependencies from the rest of your system. If you don't know what that means, you should probably do some more tinkering and come back when you're ready to roll.

### Prerequisites
Make sure you have the latest version of Python and set up a VENV where you can install dependencies. You'll also likely want an updated version of PIP.

How to update Python: [How to Update Python](https://www.pythoncentral.io/how-to-update-python/).

I suggest creating a new directory where you want to store the project, create a VENV, and ensure pip is updated in that VENV.
   ```sh
mkdir CityBot2
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
  ```

### Installation

To install CityBot2, you can clone the repository to your system and run the installer. It's recommended that you run in a virtual environment.

1. Clone the repository to your desired directory. I used /code/CityBot2.

Example:
   ```sh
git clone https://github.com/ericrosenberg1/CityBot2
  ```

2. Run the installer
To install, set permissions for the install.sh file and run it with these commands:

Example:
   ```sh
chmod +x install.sh
./install.sh
  ```

4. Edit configuration files:
Navigate to the config directory. Using the Nano editor, add your social network credentials.

Enter these commands in your terminal:
   ```sh
cd config
mv credentials.env.example credentials.env
nano credentials.env
  ```

Press CTRL+X and enter Y at the prompt to save and exit.

Then update your social_config file with details for your city. Remove the example settings from Ventura, California.
   ```sh
nano config/social_config.json
  ```
Press CTRL+X and enter Y at the prompt to save and exit.

4. Start the service:
   - `sudo systemctl start citybot`

5. Enable service at boot:
   - `sudo systemctl enable citybot`

6. Check service status:
   - `sudo systemctl status citybot`

7. View logs:
   - `tail -f logs/citybot.log`

<p align="right">(<a href="#readme-top">back to top</a>)</p>

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
After updating the config files, you can run the bot and it should automatically post to your desired social media accounts. Check the error log if something isn't working.

## Roadmap

- [ ] Create documentation
- [ ] Improve error handling
- [ ] Create a basic web GUI
- [ ] Make it easier to update information for new cities
- [ ] Create package to install and use with PyPi or apt

See the [open issues](https://github.com/ericrosenberg1/CityBot2/issues) for a full list of proposed features (and known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contributing

Contributions to CityBot2 are welcome! 

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**. If you encounter any bugs or issues, please report them by opening an issue [here](https://github.com/ericrosenberg1/CityBot2/issues).

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".

Don't forget to give the project a star!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

For support, open an issue here on GitHub. For inquiries about commercial support, please contact the author via email using the contact form at [EricRosenberg.com](https://ericrosenberg.com).

### Contributors:

<a href="https://github.com/ericrosenberg1/CityBot2/graphs/contributors">
</a>

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## License
Distributed under the GPLv3 License. See 'LICENSE.txt' for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTACT -->
<!-- CONTACT Placeholder
## Contact

Your Name - [@your_twitter](https://twitter.com/your_username) - email@example.com

Project Link: [https://github.com/your_username/repo_name](https://github.com/your_username/repo_name)

<p align="right">(<a href="#readme-top">back to top</a>)</p>
-->

## Acknowledgments
* Claude.ai for helping me create the first version of the code for this app
* [GPT4Readability](https://github.com/loevlie/GPT4Readability) – Initial version of README.md and a cool AI-driven project
* [Best-README-Template](https://github.com/othneildrew/Best-README-Template/tree/main) – Major improvemnts to the README.md file
